from sqlalchemy import create_engine, desc, asc
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.sql import and_, or_
import time
import datetime
from contextlib import contextmanager

from model import Account, Symbol, Position, Order, Execution, init_db

class Database:
    def __init__(self, db_url="postgresql://username:password@localhost/exchange"):
        """初始化数据库连接"""
        self.engine = init_db(db_url)
        self.Session = scoped_session(sessionmaker(bind=self.engine))

    def reset(self):
        """Reset the database (drop and recreate tables)"""
        reset_db(self.db_url)
        self.engine = init_db(self.db_url)

    @contextmanager
    def session_scope(self):
        """提供事务范围的数据库会话"""
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
        """创建新账户"""
        with self.session_scope() as session:
            # 检查账户是否已存在
            existing = session.query(Account).filter_by(id=account_id).first()
            if existing:
                return False, "Account already exists"

            # 创建新账户
            account = Account(id=account_id, balance=float(balance))
            session.add(account)
            return True, None

    def create_symbol(self, symbol_name, account_id, amount):
        """创建或添加股票到账户"""
        with self.session_scope() as session:
            # 检查账户是否存在
            account = session.query(Account).filter_by(id=account_id).first()
            if not account:
                return False, f"Account {account_id} does not exist"

            # 检查股票是否存在，如果不存在则创建
            symbol = session.query(Symbol).filter_by(name=symbol_name).first()
            if not symbol:
                symbol = Symbol(name=symbol_name)
                session.add(symbol)

            # 更新或创建仓位
            position = session.query(Position).filter_by(
                account_id=account_id, symbol_name=symbol_name).first()

            if position:
                position.amount += amount
            else:
                position = Position(account_id=account_id, symbol_name=symbol_name, amount=amount)
                session.add(position)

            return True, None

    def get_account(self, account_id):
        """获取账户信息"""
        with self.session_scope() as session:
            return session.query(Account).filter_by(id=account_id).first()

    def get_position(self, symbol_name, account_id):
        """获取账户持有的股票数量"""
        with self.session_scope() as session:
            position = session.query(Position).filter_by(
                account_id=account_id, symbol_name=symbol_name).first()
            return position.amount if position else 0

    def update_position(self, account_id, symbol_name, amount, session=None):
        """更新股票仓位"""
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
                # 确保股票存在
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
        """更新账户余额"""
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
        """创建新订单"""
        with self.session_scope() as session:
            # 生成订单ID
            order = Order(
                account_id=account_id,
                symbol_name=symbol_name,
                amount=amount,
                limit_price=float(limit_price),
                open_shares=amount
            )
            session.add(order)
            session.flush()  # 获取数据库生成的ID
            return order

    def get_order(self, order_id):
        """获取订单信息"""
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
                order = session.query(Order).filter_by(id=order_id).first()
                if not order:
                    return False, "Order not found"

                # Check if the order has any open shares to cancel
                if order.open_shares <= 0:
                    return False, "Order has no open shares to cancel"

                # Record the cancellation time
                cancel_time = int(time.time())

                # Get the account
                account = session.query(Account).filter_by(id=order.account_id).first()
                if not account:
                    return False, "Account not found"

                # Refund for buy orders or return shares for sell orders
                if order.amount > 0:  # Buy order
                    # Calculate refund amount based on open shares and limit price
                    refund_amount = order.open_shares * float(order.limit_price)

                    # Update account balance
                    self.logger.info(f"Refunding {refund_amount} to account {account.id} for canceled buy order {order_id}")
                    account.balance += refund_amount
                    session.add(account)

                else:  # Sell order
                    # Return shares to account position
                    symbol = order.symbol
                    return_shares = order.open_shares

                    # Get or create position
                    position = session.query(Position).filter_by(
                        account_id=account.id, symbol_name=symbol).first()
                    if position:
                        self.logger.info(f"Returning {return_shares} shares of {symbol} to account {account.id} for canceled sell order {order_id}")
                        position.amount += return_shares
                        session.add(position)
                    else:
                        # Create new position if one doesn't exist
                        self.logger.info(f"Creating new position with {return_shares} shares of {symbol} for account {account.id} from canceled sell order {order_id}")
                        new_position = Position(account_id=account.id, symbol_name=symbol, amount=return_shares)
                        session.add(new_position)

                # Update order status
                canceled_shares = order.open_shares
                order.open_shares = 0
                order.canceled_time = cancel_time
                order.canceled_shares = canceled_shares
                session.add(order)

                # Remove from order book if necessary
                # This might be a method call to matching_engine or order_book depending on your architecture
                # self.matching_engine.remove_order_from_book(order_id)

                # Commit all changes
                session.commit()

                return True, None

        except Exception as e:
            session.rollback()
            self.logger.error(f"Error canceling order {order_id}: {str(e)}")
            return False, f"Error canceling order: {str(e)}"

    def get_buy_orders(self, symbol_name):
        """获取买入订单，按价格（降序）和时间（升序）排序"""
        with self.session_scope() as session:
            return session.query(Order).filter(
                Order.symbol_name == symbol_name,
                Order.amount > 0,
                Order.open_shares > 0,
                Order.canceled_at == None
            ).order_by(desc(Order.limit_price), asc(Order.created_at)).all()

    def get_sell_orders(self, symbol_name):
        """获取卖出订单，按价格（升序）和时间（升序）排序"""
        with self.session_scope() as session:
            return session.query(Order).filter(
                Order.symbol_name == symbol_name,
                Order.amount < 0,
                Order.open_shares < 0,
                Order.canceled_at == None
            ).order_by(asc(Order.limit_price), asc(Order.created_at)).all()

    def record_execution(self, order_id, shares, price, session=None):
        """记录订单执行情况"""
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
        """执行订单的一部分"""
        close_session = False
        if session is None:
            session = self.Session()
            close_session = True

        try:
            execute_shares = min(abs(shares), abs(order.open_shares))
            if execute_shares <= 0:
                return False

            # 更新开放股数
            if order.amount > 0:  # 买入
                order.open_shares -= execute_shares
            else:  # 卖出
                order.open_shares += execute_shares

            # 记录执行情况
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
        Get order status for XML response

        Returns:
            list: XML elements representing order status
        """
        if session is None:
            session = self.Session()
            session.add(order)
            close_session = True
        result = []

        # Add open status if open
        if order.open_shares != 0 and order.canceled_at is None:
            result.append(f'<open shares="{abs(order.open_shares)}"/>')

        # Add canceled status if canceled
        if order.canceled_at is not None:
            result.append(f'<canceled shares="{abs(order.amount) - sum(e[0] for e in order.executions)}" time="{int(order.canceled_at.timestamp())}"/>')

        # Add execution statuses
        for execution in order.executions:
            result.append(f'<executed shares="{execution.shares}" price="{execution.price}" time="{int(execution.executed_at.timestamp())}"/>')

        return result
