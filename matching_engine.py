import threading
import logging
import time
import random
from sqlalchemy.exc import OperationalError
from database import Account, Position
from collections import defaultdict

logger = logging.getLogger(__name__)

class MatchingEngine:
    def __init__(self, database):
        self.database = database
        # Use symbol-scoped lock for in-process serialization.
        # Cross-process consistency is handled by DB row locks.
        self.symbol_locks = defaultdict(threading.Lock)
        self.logger = logging.getLogger(__name__)
    
    def get_symbol_lock(self, symbol):
        """Get the lock for a specific symbol"""
        return self.symbol_locks[symbol]
        
    def match_orders(self, new_order, session):
        """
        Match new order against DB-backed shared order book.
        Returns a list of executed orders.
        """
        session.add(new_order)
        symbol = new_order.symbol_name
        logger.info(f"Attempting to match order {new_order.id}: {new_order.amount} shares of {symbol} at limit {new_order.limit_price}")

        executed_orders = []

        # Determine if this is a buy or sell order
        is_buy = new_order.amount > 0

        # Use open_shares as it reflects the current state.
        remaining_shares = abs(new_order.open_shares)

        while remaining_shares > 0:
            # Query shared DB order book with price priority and FIFO tie-break.
            opposite_order = self.database.get_best_matching_order(
                symbol_name=symbol,
                is_buy_order=is_buy,
                limit_price=new_order.limit_price,
                session=session
            )
            if not opposite_order:
                logger.info(f"No more compatible orders for order {new_order.id}")
                break

            # Calculate how many shares can be executed in this match
            opposite_remaining = abs(opposite_order.open_shares)
            executable_shares = min(remaining_shares, opposite_remaining)

            if executable_shares <= 0:
                continue

            logger.info(f"Matching {executable_shares} shares between orders {new_order.id} and {opposite_order.id}")

            # Determine execution price (use the price of the order that was open first)
            execution_price = opposite_order.limit_price if opposite_order.created_at <= new_order.created_at else new_order.limit_price
            logger.info(f"Execution price: {execution_price}")

            # Execute the orders
            buyer_id = new_order.account_id if is_buy else opposite_order.account_id
            seller_id = opposite_order.account_id if is_buy else new_order.account_id

            # Record execution for the new order
            new_order_execution = self.database.execute_order_part(
                new_order,
                executable_shares,
                execution_price,
                session
            )

            # Record execution for the opposite order
            opposite_order_execution = self.database.execute_order_part(
                opposite_order,
                executable_shares,
                execution_price,
                session
            )

            # Update account positions and balances
            # Calculate total value of the transaction
            total_value = float(execution_price) * executable_shares

            # Update buyer's position (add shares)
            self.database.update_position(buyer_id, new_order.symbol_name, executable_shares, session)

            # Update seller's balance (add money)
            self.database.update_account_balance(seller_id, total_value, session)

            logger.info(f"Executed {executable_shares} shares at {execution_price}: " +
                        f"Order {new_order.id} has {new_order.open_shares} open shares, " +
                        f"Order {opposite_order.id} has {opposite_order.open_shares} open shares")

            # Record executed transactions for return
            executed_orders.append((new_order_execution, opposite_order_execution))

            # Update remaining shares to match
            remaining_shares -= executable_shares
            logger.info(
                f"Post-match: order {new_order.id} open={new_order.open_shares}, "
                f"order {opposite_order.id} open={opposite_order.open_shares}"
            )

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
                        self.match_orders(order, session)

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
