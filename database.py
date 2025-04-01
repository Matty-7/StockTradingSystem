from sqlalchemy import create_engine, desc, asc
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.sql import and_, or_
import time
import datetime
from contextlib import contextmanager
import logging # Import logging

from model import Account, Symbol, Position, Order, Execution, init_db

# Setup basic logging
logging.basicConfig(level=logging.INFO)

class Database:
    def __init__(self, db_url="postgresql://username:password@localhost/exchange"):
        """initialize the database connection"""
        self.engine = init_db(db_url)
        self.Session = scoped_session(sessionmaker(bind=self.engine))
        self.logger = logging.getLogger(__name__) # Add logger instance

    def reset(self):
        """Reset the database (drop and recreate tables)"""
        reset_db(self.db_url)
        self.engine = init_db(self.db_url)

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

    def get_position(self, symbol_name, account_id):
        """get the number of stocks the account holds"""
        with self.session_scope() as session:
            position = session.query(Position).filter_by(
                account_id=account_id, symbol_name=symbol_name).first()
            return position.amount if position else 0

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

    def create_order(self, account_id, symbol_name, amount, limit_price):
        """create a new order"""
        with self.session_scope() as session:
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
            return order

    def get_order(self, order_id):
        """get the order information"""
        with self.session_scope() as session:
            return session.query(Order).filter_by(id=order_id).first()

    def cancel_order(self, order_id):
        """
        Cancel an open order and refund/return appropriate assets.
        Returns (success, error_message)
        """
        try:
            with self.session_scope() as session:
                # Get the order and verify it exists
                # Use with_for_update to lock the order row
                order = session.query(Order).filter_by(id=order_id).with_for_update().first()
                if not order:
                    return False, "Order not found"

                # Check if the order has any open shares to cancel (positive for buy, negative for sell)
                if order.open_shares == 0:
                    return False, "Order already fully executed or canceled"

                # Prevent canceling already canceled orders
                if order.canceled_at is not None:
                    return False, "Order already canceled"

                # Record the cancellation time as datetime
                cancel_time = datetime.datetime.utcnow()

                # Get the account
                account = session.query(Account).filter_by(id=order.account_id).with_for_update().first()
                if not account:
                    # This shouldn't happen if DB constraints are set up
                    return False, f"Account {order.account_id} not found for order {order_id}"

                # Store the amount of shares being canceled (always positive)
                canceled_shares_amount = abs(order.open_shares)

                # Refund for buy orders or return shares for sell orders
                if order.amount > 0:  # Buy order
                    # Calculate refund amount based on open shares and limit price
                    refund_amount = canceled_shares_amount * float(order.limit_price)

                    # Update account balance
                    self.logger.info(f"Refunding {refund_amount} to account {account.id} for canceled buy order {order_id}")
                    account.balance += refund_amount
                    session.add(account)

                else:  # Sell order
                    # Return shares to account position
                    symbol_name = order.symbol_name # Use symbol_name
                    return_shares = canceled_shares_amount # Use the positive amount

                    # Get or create position
                    position = session.query(Position).filter_by(
                        account_id=account.id, symbol_name=symbol_name).with_for_update().first()

                    if position:
                        self.logger.info(f"Returning {return_shares} shares of {symbol_name} to account {account.id} for canceled sell order {order_id}")
                        position.amount += return_shares
                        session.add(position)
                    else:
                        # Create new position if one doesn't exist
                        # This case might indicate an inconsistency if a sell order was placed without a position
                        self.logger.warning(f"Creating new position with {return_shares} shares of {symbol_name} for account {account.id} from canceled sell order {order_id}")
                        new_position = Position(account_id=account.id, symbol_name=symbol_name, amount=return_shares)
                        session.add(new_position)

                # Update order status
                order.open_shares = 0
                order.canceled_at = cancel_time # Store datetime object
                # order.canceled_shares is not a standard field in the model provided
                # We can derive canceled shares later if needed: total amount - executed shares
                session.add(order)

                # Commit all changes
                # session.commit() # Handled by session_scope context manager

                self.logger.info(f"Successfully canceled order {order_id} for account {account.id}")
                return True, None

        except Exception as e:
            # session.rollback() # Handled by session_scope context manager
            self.logger.exception(f"Error canceling order {order_id}: {str(e)}") # Use logger.exception
            return False, f"Error canceling order: {str(e)}"

    def get_buy_orders(self, symbol_name):
        """get the buy orders, sorted by price (descending) and time (ascending)"""
        with self.session_scope() as session:
            return session.query(Order).filter(
                Order.symbol_name == symbol_name,
                Order.amount > 0,
                Order.open_shares > 0,
                Order.canceled_at == None
            ).order_by(desc(Order.limit_price), asc(Order.created_at)).all()

    def get_sell_orders(self, symbol_name):
        """get the sell orders, sorted by price (ascending) and time (ascending)"""
        with self.session_scope() as session:
            return session.query(Order).filter(
                Order.symbol_name == symbol_name,
                Order.amount < 0,
                Order.open_shares < 0, # Keep this condition
                Order.canceled_at == None
            ).order_by(asc(Order.limit_price), asc(Order.created_at)).all()

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

    def get_status(self, order, session=None):
        """
        Get order status information, including open, executed, and canceled parts.

        Args:
            order (Order): The order object (must be managed by a session).
            session (Session, optional): The database session. If None, uses internal scope.

        Returns:
            tuple: (list_of_status_xml_strings, error_message_or_None)
        """
        manage_session = False
        if session is None:
            session = self.Session()
            manage_session = True
            session.add(order) # Ensure the object is attached if passed from outside

        results = []
        error_msg = None

        try:
            # Reload the order within the current session to ensure fresh data, especially relationships
            session.refresh(order)

            # Add open status if applicable (not canceled and has open shares)
            if order.open_shares != 0 and order.canceled_at is None:
                results.append(f'<open shares="{abs(order.open_shares)}"/>')

            # Fetch executions eagerly if needed or rely on relationship loading
            # Ensure executions are loaded within the session
            executions = session.query(Execution).filter(Execution.order_id == order.id).order_by(Execution.executed_at).all()
            total_executed_shares = sum(ex.shares for ex in executions)

            # Add executed parts
            for execution in executions:
                if execution.executed_at:
                    exec_time = int(execution.executed_at.timestamp())
                else:
                    # Fallback or error handling if timestamp is missing
                    exec_time = int(time.time())
                    self.logger.warning(f"Execution {execution.id} for order {order.id} missing executed_at timestamp.")
                results.append(f'<executed shares="{execution.shares}" price="{execution.price}" time="{exec_time}"/>')

            # Add canceled status if applicable
            if order.canceled_at is not None:
                # Calculate canceled shares: Total initial amount - total executed amount
                canceled_shares = abs(order.amount) - total_executed_shares
                cancel_time = int(order.canceled_at.timestamp())
                # Ensure canceled shares is not negative due to potential float issues
                canceled_shares = max(0, canceled_shares)
                results.append(f'<canceled shares="{canceled_shares}" time="{cancel_time}"/>')

        except Exception as e:
            self.logger.exception(f"Error getting status for order {order.id}: {e}")
            error_msg = f"Error retrieving status: {e}"
            results = [] # Clear potentially partial results on error
        finally:
            if manage_session:
                session.close()

        return results, error_msg

    def get_order_executions(self, order_id, session=None):
        """Get all execution records for a specific order ID."""
        manage_session = False
        if session is None:
            session = self.Session()
            manage_session = True

        try:
            executions = session.query(Execution).filter_by(order_id=order_id).order_by(asc(Execution.executed_at)).all()
            return executions
        except Exception as e:
            self.logger.error(f"Error fetching executions for order {order_id}: {e}")
            return [] # Return empty list on error
        finally:
            if manage_session:
                session.close()
