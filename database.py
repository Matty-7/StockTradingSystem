from sqlalchemy import create_engine, desc, asc
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.sql import and_, or_
import time
import datetime
from contextlib import contextmanager
import logging

from model import Account, Symbol, Position, Order, Execution, init_db

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

    def get_order(self, order_id, session=None):
        """get the order information"""
        close_session = False
        if session is None:
            session = self.Session()
            close_session = True

        try:
            order = session.query(Order).filter_by(id=order_id).first()
            return order
        finally:
            if close_session:
                session.close()

    def cancel_order(self, order_id, requesting_account_id):
        """
        Cancel an open order and refund/return appropriate assets.
        Checks if the requesting_account_id matches the order's account_id.

        Args:
            order_id (int): The ID of the order to cancel.
            requesting_account_id (str): The ID of the account making the cancel request.

        Returns:
            (success, error_message)
        """
        with self.session_scope() as session:
            try:
                # Get the order and verify it exists
                # Use with_for_update to lock the order row
                order = session.query(Order).filter_by(id=order_id).with_for_update().first()
                if not order:
                    return False, "Order not found"

                # === Permission Check ===
                if order.account_id != requesting_account_id:
                    self.logger.warning(f"Permission denied: Account {requesting_account_id} tried to cancel order {order_id} owned by {order.account_id}")
                    return False, "Permission denied: Cannot cancel order belonging to another account"

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
                    else:
                        # Create new position if one doesn't exist
                        # This case might indicate an inconsistency if a sell order was placed without a position
                        self.logger.warning(f"Creating new position with {return_shares} shares of {symbol_name} for account {account.id} from canceled sell order {order_id}")
                        new_position = Position(account_id=account.id, symbol_name=symbol_name, amount=return_shares)
                        session.add(new_position)

                # Update order status
                order.open_shares = 0
                order.canceled_at = cancel_time # Store datetime object
                
                self.logger.info(f"Successfully canceled order {order_id} for account {account.id}")
                return True, None
            
            except Exception as e:
                self.logger.exception(f"Error canceling order {order_id}: {e}")
                return False, f"Error canceling order: {str(e)}"

    def get_buy_orders(self, symbol_name, session=None):
        """get open buy orders for a symbol"""
        close_session = False
        if session is None:
            session = self.Session()
            close_session = True

        try:
            orders = session.query(Order).filter(
                Order.symbol_name == symbol_name,
                Order.amount > 0,
                Order.open_shares > 0,
                Order.canceled_at == None
            ).all()
            return orders
        finally:
            if close_session:
                session.close()

    def get_sell_orders(self, symbol_name, session=None):
        """get open sell orders for a symbol"""
        close_session = False
        if session is None:
            session = self.Session()
            close_session = True
            
        try:
            orders = session.query(Order).filter(
                Order.symbol_name == symbol_name,
                Order.amount < 0,
                Order.open_shares < 0,
                Order.canceled_at == None
            ).all()
            return orders
        finally:
            if close_session:
                session.close()

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

    def get_status(self, order_id, session=None):
        """
        Get the status and details of a specific order
        Returns a dict with status details including executions
        """
        close_session = False
        if session is None:
            session = self.Session()
            close_session = True

        try:
            # Get order information
            order = session.query(Order).filter_by(id=order_id).first()
            if not order:
                return {"status": "error", "error": f"Order {order_id} not found"}
            
            # Format creation time as ISO 8601
            created_at_iso = order.created_at.isoformat() if order.created_at else None
            
            # Build basic status
            status_info = {
                "id": order.id,
                "account_id": order.account_id,
                "symbol": order.symbol_name,
                "amount": order.amount,
                "limit_price": float(order.limit_price),
                "created_at": created_at_iso,
                "open_shares": order.open_shares,
                "canceled": order.canceled_at is not None
            }
            
            # Add canceled time if applicable
            if order.canceled_at:
                status_info["canceled_at"] = order.canceled_at.isoformat()
            
            # Get all executions for this order
            executions = session.query(Execution).filter_by(order_id=order_id).all()
            
            # Format and add executions if any
            if executions:
                status_info["executions"] = []
                for execution in executions:
                    exec_info = {
                        "shares": execution.shares,
                        "price": float(execution.price),
                        "time": execution.executed_at.isoformat() if execution.executed_at else None
                    }
                    status_info["executions"].append(exec_info)
                    
                # Calculate summary statistics
                total_shares = sum(e.shares for e in executions)
                if total_shares > 0:  # Avoid division by zero
                    avg_price = sum(e.shares * float(e.price) for e in executions) / total_shares
                    status_info["total_executed_shares"] = total_shares
                    status_info["avg_executed_price"] = avg_price
            else:
                status_info["executions"] = []
                
            return status_info
        except Exception as e:
            self.logger.exception(f"Error getting order status for order {order_id}: {e}")
            return {"status": "error", "error": f"Error retrieving order status: {str(e)}"}
        finally:
            if close_session:
                session.close()

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
