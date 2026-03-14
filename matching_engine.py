import threading
import logging
import os
import time
import random
from sortedcontainers import SortedList
from sqlalchemy.exc import OperationalError
from database import Account, Position
from collections import defaultdict

logger = logging.getLogger(__name__)

_MATCH_LATENCY_FILE = os.environ.get('MATCH_LATENCY_FILE', '')


def _log_match_latency(elapsed: float) -> None:
    """Append a single matching-engine latency sample (seconds) to the shared file."""
    if not _MATCH_LATENCY_FILE:
        return
    try:
        with open(_MATCH_LATENCY_FILE, 'a') as f:
            f.write(f"{elapsed}\n")
    except OSError:
        pass


class InMemoryOrderBook:
    """Per-process in-memory order book for fast match-candidate lookup.

    Correctness model (hybrid):
    - This book is an OPTIMISTIC CACHE.  The DB row lock (WITH FOR UPDATE SKIP LOCKED)
      remains the authoritative arbiter.
    - Stale entries (orders already executed by another worker) are discovered lazily
      when the DB FOR UPDATE returns nothing; they are then pruned.
    - After exhausting all in-memory candidates, match_orders() always falls back to
      one full DB scan to catch orders placed by other workers that are not yet in
      this process's cache.
    """

    def __init__(self):
        self._lock = threading.Lock()
        # asks: (price ASC, created_at ASC, order_id ASC) — lowest ask first
        self._asks: SortedList = SortedList(key=lambda x: (x[0], x[1], x[2]))
        # bids: (-price ASC, created_at ASC, order_id ASC) — highest bid first
        self._bids: SortedList = SortedList(key=lambda x: (x[0], x[1], x[2]))
        self._ask_ids: set = set()
        self._bid_ids: set = set()

    def load_from_db(self, session):
        """Populate from the DB snapshot of all currently open orders."""
        from model import Order
        open_orders = session.query(Order).filter(
            Order.open_shares != 0,
            Order.canceled_at.is_(None),
        ).all()
        with self._lock:
            for o in open_orders:
                self._insert(o.id, float(o.limit_price), o.created_at, o.open_shares > 0)

    def _insert(self, order_id: int, price: float, created_at, is_buy: bool) -> None:
        if is_buy:
            if order_id not in self._bid_ids:
                self._bids.add((-price, created_at, order_id))
                self._bid_ids.add(order_id)
        else:
            if order_id not in self._ask_ids:
                self._asks.add((price, created_at, order_id))
                self._ask_ids.add(order_id)

    def add(self, order) -> None:
        with self._lock:
            self._insert(order.id, float(order.limit_price), order.created_at, order.open_shares > 0)

    def remove(self, order_id: int, is_buy: bool) -> None:
        with self._lock:
            if is_buy and order_id in self._bid_ids:
                self._bids.remove(next(e for e in self._bids if e[2] == order_id))
                self._bid_ids.discard(order_id)
            elif not is_buy and order_id in self._ask_ids:
                self._asks.remove(next(e for e in self._asks if e[2] == order_id))
                self._ask_ids.discard(order_id)

    def best_candidate(self, is_buy: bool, limit_price: float):
        """Return (price, created_at, order_id) of the best in-memory counterpart, or None."""
        with self._lock:
            if is_buy:
                if self._asks and self._asks[0][0] <= limit_price:
                    return self._asks[0]
            else:
                if self._bids and -self._bids[0][0] >= limit_price:
                    return self._bids[0]
        return None


class MatchingEngine:
    def __init__(self, database):
        self.database = database
        # Use symbol-scoped lock for in-process serialization.
        # Cross-process consistency is handled by DB row locks.
        self.symbol_locks = defaultdict(threading.Lock)
        self.order_book = InMemoryOrderBook()
        self.logger = logging.getLogger(__name__)

    def get_symbol_lock(self, symbol):
        """Get the lock for a specific symbol"""
        return self.symbol_locks[symbol]

    def load_order_book(self, session) -> None:
        """Call once at worker startup to warm the in-memory book."""
        self.order_book.load_from_db(session)

    def match_orders(self, new_order, session):
        """
        Match new order against the order book.

        Fast path: check the per-process in-memory book to find candidates without
        a DB query.  Each candidate is then confirmed with a DB FOR UPDATE lock.
        Slow path (fallback): after exhausting in-memory candidates, run one full DB
        scan to catch orders placed by other worker processes since this book was last
        synced.
        """
        session.add(new_order)
        symbol = new_order.symbol_name
        is_buy = new_order.amount > 0
        remaining_shares = abs(new_order.open_shares)
        executed_orders = []

        while remaining_shares > 0:
            candidate = self.order_book.best_candidate(is_buy, float(new_order.limit_price))

            if candidate is not None:
                # Confirm the candidate is still open and lock it in the DB.
                from model import Order as OrderModel
                opposite_order = session.query(OrderModel).filter(
                    OrderModel.id == candidate[2],
                    OrderModel.open_shares != 0,
                    OrderModel.canceled_at.is_(None),
                ).with_for_update(skip_locked=True).first()

                if opposite_order is None:
                    # Stale cache entry — prune and try next candidate.
                    self.order_book.remove(candidate[2], not is_buy)
                    continue
            else:
                # No in-memory candidate: fall back to full DB scan (catches
                # orders from other worker processes not yet in this cache).
                opposite_order = self.database.get_best_matching_order(
                    symbol_name=symbol,
                    is_buy_order=is_buy,
                    limit_price=new_order.limit_price,
                    session=session,
                )
                if not opposite_order:
                    break
                # Sync the found order into the local book for future lookups.
                self.order_book.add(opposite_order)

            opposite_remaining = abs(opposite_order.open_shares)
            executable_shares = min(remaining_shares, opposite_remaining)
            if executable_shares <= 0:
                continue

            execution_price = (opposite_order.limit_price
                               if opposite_order.created_at <= new_order.created_at
                               else new_order.limit_price)
            buyer_id = new_order.account_id if is_buy else opposite_order.account_id
            seller_id = opposite_order.account_id if is_buy else new_order.account_id
            total_value = float(execution_price) * executable_shares

            new_order_execution = self.database.execute_order_part(
                new_order, executable_shares, execution_price, session)
            opposite_order_execution = self.database.execute_order_part(
                opposite_order, executable_shares, execution_price, session)
            self.database.update_position(buyer_id, symbol, executable_shares, session)
            self.database.update_account_balance(seller_id, total_value, session)

            executed_orders.append((new_order_execution, opposite_order_execution))
            remaining_shares -= executable_shares

            # Keep in-memory book in sync with what we just executed.
            if opposite_order.open_shares == 0:
                self.order_book.remove(opposite_order.id, not is_buy)

        return executed_orders

    def place_order(self, account_id, symbol, amount, limit_price):
        """Place an order and try to match it"""
        max_retries = 8
        backoff_seconds = 0.02

        for attempt in range(max_retries):
            order_id = None
            success = False
            error_msg = None

            # Use symbol-specific lock instead of global lock
            with self.get_symbol_lock(symbol):
                try:
                    with self.database.session_scope() as session:
                        # Use the imported Account model directly
                        account = session.query(Account).filter_by(id=account_id).with_for_update().first()
                        if not account:
                            error_msg = "Account not found"
                            return success, error_msg, order_id

                        # Buy order, check if balance is sufficient
                        if amount > 0:  # Buy
                            cost = amount * float(limit_price)
                            # Allow order if balance is exactly equal to cost or greater
                            if account.balance < cost:
                                error_msg = "Insufficient funds"
                                return success, error_msg, order_id

                            # Deduct balance (optimistically, within transaction)
                            self.logger.info(f"Deducting {cost} from account {account_id} for potential buy order")
                            account.balance -= cost
                        else:  # Sell
                            # Check if shares are sufficient
                            # Use the imported Position model directly
                            position = session.query(Position).filter_by(
                                account_id=account_id, symbol_name=symbol).with_for_update().first()
                            if not position or position.amount < abs(amount):
                                error_msg = "Insufficient shares"
                                return success, error_msg, order_id

                            # Deduct shares (optimistically, within transaction)
                            self.logger.info(f"Deducting {abs(amount)} shares of {symbol} from account {account_id} for potential sell order")
                            position.amount += amount  # amount is negative

                        # Create order
                        order = self.database.create_order(account_id, symbol, amount, limit_price, session)
                        session.flush()  # Flush to get the order ID before matching
                        order_id = order.id
                        self.logger.info(f"Created order {order_id}. Attempting match.")

                        # Try to match the order within the same transaction
                        _match_start = time.time()
                        self.match_orders(order, session)
                        _log_match_latency(time.time() - _match_start)

                        # Add the order to the in-memory book if it has remaining open shares.
                        # Done after matching so the book reflects the post-match state.
                        if order.open_shares != 0:
                            self.order_book.add(order)

                        # If we reached here without exceptions, the DB transaction will commit
                        success = True
                        self.logger.info(f"Order {order_id} placed and matched successfully (or added to book).")
                        return success, error_msg, order_id

                except OperationalError as e:
                    # Retry deadlock/serialization failures instead of returning internal error.
                    pgcode = getattr(getattr(e, "orig", None), "pgcode", None)
                    retryable = pgcode in {"40P01", "40001"}
                    if retryable and attempt < max_retries - 1:
                        wait_s = backoff_seconds * (2 ** attempt) + random.uniform(0.0, 0.01)
                        self.logger.warning(
                            f"Retrying place_order after transient DB error pgcode={pgcode}, "
                            f"attempt {attempt + 1}/{max_retries}, sleep={wait_s:.3f}s"
                        )
                        time.sleep(wait_s)
                        continue
                    self.logger.exception(f"Operational error during place_order for account {account_id}, symbol {symbol}: {e}")
                    error_msg = f"Internal server error during order placement: {str(e)}"
                    return success, error_msg, order_id

                except Exception as e:
                    # Log the exception that occurred within the transaction scope
                    self.logger.exception(f"Error during place_order for account {account_id}, symbol {symbol}: {e}")
                    error_msg = f"Internal server error during order placement: {str(e)}"
                    return success, error_msg, order_id

        return False, "Internal server error during order placement: retry budget exceeded", None
