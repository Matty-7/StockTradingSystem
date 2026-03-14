from sqlalchemy import create_engine, event, asc, desc, update as sql_update, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import sessionmaker, scoped_session
from contextlib import contextmanager
import logging
import os

from model import Account, Symbol, Position, Order, Execution

class Database:
    def __init__(self, db_url="postgresql://username:password@localhost/exchange"):
        """initialize the database connection"""
        self.db_url = db_url

        # Each worker is single-threaded (one request at a time), so it only ever
        # needs 1–2 connections from the pool simultaneously.  Keeping pool_size
        # proportional to worker count prevents idle connections from accumulating
        # inside PostgreSQL's lock manager and shared-buffer structures, which
        # otherwise inflate per-query latency at higher core counts.
        # Scale pool proportionally: total open connections ≤ ~40 regardless of
        # worker count, keeping PostgreSQL's backend overhead manageable.
        # Formula: pool_size = clamp(16 // workers, 2, 8)
        #   1 worker  → 8  (16 total + 1 LISTEN = 17)
        #   2 workers → 8  (32 total + 2 LISTEN = 34)
        #   4 workers → 4  (32 total + 4 LISTEN = 36)
        #   8 workers → 2  (32 total + 8 LISTEN = 40)
        num_workers = int(os.environ.get('CPU_CORES', os.cpu_count() or 4))
        pool_size = max(2, min(8, 16 // num_workers))
        max_overflow = max(1, pool_size // 2)      # small burst headroom

        self.engine = create_engine(
            self.db_url,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_timeout=30,
            pool_recycle=1800,
            echo_pool=False,
        )

        # Disable synchronous WAL commits per-connection.
        # This removes the fsync round-trip on every COMMIT (~1-3 ms saved per transaction).
        # Trade-off: up to ~200 ms of committed data could be lost on a hard crash,
        # but the database will never be left in a corrupt state.
        @event.listens_for(self.engine, "connect")
        def _set_async_commit(dbapi_conn, _record):
            cur = dbapi_conn.cursor()
            cur.execute("SET synchronous_commit = off")
            cur.close()

        # Create a scoped session factory
        self.Session = scoped_session(sessionmaker(bind=self.engine))
        self.logger = logging.getLogger(__name__)

    @contextmanager
    def session_scope(self):
        """provide a database session for transaction"""
        session = self.Session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def create_account(self, account_id, balance):
        """create a new account"""
        with self.session_scope() as session:
            # check if the account already exists
            existing = session.query(Account).filter_by(id=account_id).first()
            if existing:
                return False, "Account already exists"

            # create a new account
            account = Account(id=account_id, balance=float(balance))
            session.add(account)
            return True, None

    def create_symbol(self, symbol_name, account_id, amount):
        """create or add a stock to the account"""
        with self.session_scope() as session:
            # check if the account exists
            account = session.query(Account).filter_by(id=account_id).first()
            if not account:
                return False, f"Account {account_id} does not exist"

            # check if the stock exists, if not, create it
            symbol = session.query(Symbol).filter_by(name=symbol_name).first()
            if not symbol:
                symbol = Symbol(name=symbol_name)
                session.add(symbol)

            # update or create a position
            position = session.query(Position).filter_by(
                account_id=account_id, symbol_name=symbol_name).first()

            if position:
                position.amount += amount
            else:
                position = Position(account_id=account_id, symbol_name=symbol_name, amount=amount)
                session.add(position)

            return True, None

    def get_account(self, account_id):
        """get the account information"""
        with self.session_scope() as session:
            return session.query(Account).filter_by(id=account_id).first()

    def update_position(self, account_id, symbol_name, amount, session=None):
        """Update stock position via upsert (INSERT … ON CONFLICT DO UPDATE).
        No prior SELECT needed; the database resolves insert-vs-update atomically."""
        close_session = False
        if session is None:
            session = self.Session()
            close_session = True

        try:
            stmt = (
                pg_insert(Position)
                .values(account_id=account_id, symbol_name=symbol_name, amount=amount)
                .on_conflict_do_update(
                    index_elements=["account_id", "symbol_name"],
                    set_={"amount": Position.amount + amount},
                )
            )
            session.execute(stmt)
            if close_session:
                session.commit()
        except Exception:
            if close_session:
                session.rollback()
            raise
        finally:
            if close_session:
                session.close()

    def update_account_balance(self, account_id, amount, session=None):
        """Update account balance. Uses ORM object if already in session (no extra SELECT),
        otherwise issues a direct UPDATE."""
        close_session = False
        if session is None:
            session = self.Session()
            close_session = True

        try:
            account = session.identity_map.get((Account, (account_id,)))
            if account is not None:
                account.balance += amount
            else:
                session.execute(
                    sql_update(Account)
                    .where(Account.id == account_id)
                    .values(balance=Account.balance + amount)
                    .execution_options(synchronize_session=False)
                )
            if close_session:
                session.commit()
        except Exception:
            if close_session:
                session.rollback()
            raise
        finally:
            if close_session:
                session.close()

    def create_order(self, account_id, symbol_name, amount, limit_price, session=None):
        """create a new order"""
        close_session = False
        if session is None:
            session = self.Session()
            close_session = True

        try:
            order = Order(
                account_id=account_id,
                symbol_name=symbol_name,
                amount=amount,
                limit_price=float(limit_price),
                open_shares=amount
            )
            session.add(order)
            session.flush()
            if close_session:
                session.commit()
            return order
        except Exception:
            if close_session:
                session.rollback()
            raise
        finally:
            if close_session:
                session.close()


    def get_best_matching_order(self, symbol_name, is_buy_order, limit_price, session):
        """
        Get the best open opposite-side order for matching.

        Args:
            symbol_name (str): Symbol to match.
            is_buy_order (bool): True if incoming order is buy, False if incoming is sell.
            limit_price (float): Incoming order limit.
            session: Active SQLAlchemy session.
        """
        if is_buy_order:
            # Incoming buy matches best (lowest price) sell orders first.
            return session.query(Order).filter(
                Order.symbol_name == symbol_name,
                Order.open_shares < 0,
                Order.canceled_at == None,
                Order.limit_price <= float(limit_price)
            ).order_by(
                asc(Order.limit_price),
                asc(Order.created_at),
                asc(Order.id)
            ).with_for_update(skip_locked=True).first()

        # Incoming sell matches best (highest price) buy orders first.
        return session.query(Order).filter(
            Order.symbol_name == symbol_name,
            Order.open_shares > 0,
            Order.canceled_at == None,
            Order.limit_price >= float(limit_price)
        ).order_by(
            desc(Order.limit_price),
            asc(Order.created_at),
            asc(Order.id)
        ).with_for_update(skip_locked=True).first()

    def record_execution(self, order_id, shares, price, session=None):
        """Record an order execution."""
        close_session = False
        if session is None:
            session = self.Session()
            close_session = True

        try:
            session.add(Execution(order_id=order_id, shares=shares, price=price))
            if close_session:
                session.commit()
        except Exception:
            if close_session:
                session.rollback()
            raise
        finally:
            if close_session:
                session.close()

    def notify_new_order(self, order, session) -> None:
        """Broadcast a newly placed open order to all worker processes via pg_notify.

        Payload format: "<order_id>,<is_buy>,<price>,<created_at_iso>"
        Receivers add the order directly to their in-memory book, eliminating the
        DB fallback scan for cross-worker orders.
        """
        is_buy = 1 if order.open_shares > 0 else 0
        payload = f"{order.id},{is_buy},{float(order.limit_price)},{order.created_at.isoformat()}"
        session.execute(text("SELECT pg_notify('new_order', :payload)"), {"payload": payload})

    def execute_order_part(self, order, shares, price, session=None) -> None:
        """Update open_shares on an order and record the execution."""
        close_session = False
        if session is None:
            session = self.Session()
            close_session = True

        try:
            execute_shares = min(abs(shares), abs(order.open_shares))
            if execute_shares <= 0:
                return

            if order.amount > 0:  # buy
                order.open_shares -= execute_shares
            else:  # sell
                order.open_shares += execute_shares

            self.record_execution(order.id, execute_shares, price, session)

            if close_session:
                session.commit()
        except Exception:
            if close_session:
                session.rollback()
            raise
        finally:
            if close_session:
                session.close()

