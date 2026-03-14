from sqlalchemy import create_engine, asc, desc
from sqlalchemy.orm import sessionmaker, scoped_session
from contextlib import contextmanager
import logging

from model import Account, Symbol, Position, Order, Execution

# Setup basic logging
logging.basicConfig(level=logging.INFO)

class Database:
    def __init__(self, db_url="postgresql://username:password@localhost/exchange"):
        """initialize the database connection"""
        self.db_url = db_url
        # Configure the SQLAlchemy engine with optimized connection pool settings
        self.engine = create_engine(
            self.db_url,
            pool_size=20,               # Maximum number of connections to keep open
            max_overflow=30,            # Maximum number of connections to create above pool_size
            pool_timeout=30,            # Seconds to wait before giving up on getting a connection
            pool_recycle=1800,          # Recycle connections after 30 minutes
            echo_pool=True              # Log pool events for debugging
        )
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
        except:
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
        """update the stock position"""
        close_session = False
        if session is None:
            session = self.Session()
            close_session = True

        try:
            position = session.query(Position).filter_by(
                account_id=account_id, symbol_name=symbol_name).first()

            if position:
                position.amount += amount
            else:
                # ensure the stock exists
                symbol = session.query(Symbol).filter_by(name=symbol_name).first()
                if not symbol:
                    symbol = Symbol(name=symbol_name)
                    session.add(symbol)

                position = Position(account_id=account_id, symbol_name=symbol_name, amount=amount)
                session.add(position)

            if close_session:
                session.commit()
        except:
            if close_session:
                session.rollback()
            raise
        finally:
            if close_session:
                session.close()

    def update_account_balance(self, account_id, amount, session=None):
        """update the account balance"""
        close_session = False
        if session is None:
            session = self.Session()
            close_session = True

        try:
            account = session.query(Account).filter_by(id=account_id).first()
            if account:
                account.balance += amount

                if close_session:
                    session.commit()
                return True
            return False
        except:
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
            # generate the order ID
            order = Order(
                account_id=account_id,
                symbol_name=symbol_name,
                amount=amount,
                limit_price=float(limit_price),
                open_shares=amount
            )
            session.add(order)
            session.flush()  # get the ID generated by the database
            
            if close_session:
                session.commit()
            return order
        except:
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
        """record the order execution"""
        close_session = False
        if session is None:
            session = self.Session()
            close_session = True

        try:
            execution = Execution(
                order_id=order_id,
                shares=shares,
                price=price
            )
            session.add(execution)

            if close_session:
                session.commit()
        except:
            if close_session:
                session.rollback()
            raise
        finally:
            if close_session:
                session.close()

    def execute_order_part(self, order, shares, price, session=None):
        """execute a part of the order"""
        close_session = False
        if session is None:
            session = self.Session()
            close_session = True

        try:
            execute_shares = min(abs(shares), abs(order.open_shares))
            if execute_shares <= 0:
                return False

            # update the open shares
            if order.amount > 0:  # buy
                order.open_shares -= execute_shares
            else:  # sell
                order.open_shares += execute_shares

            # record the execution
            self.record_execution(order.id, execute_shares, price, session)

            if close_session:
                session.commit()
            return True
        except:
            if close_session:
                session.rollback()
            raise
        finally:
            if close_session:
                session.close()

