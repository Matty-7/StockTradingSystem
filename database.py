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

    def update_position(self, symbol_name, account_id, amount, session=None):
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
        """取消未执行的订单"""
        with self.session_scope() as session:
            order = session.query(Order).filter_by(id=order_id).first()
            if not order:
                return False, "Order not found"

            if order.canceled_at is not None or order.open_shares == 0:
                return False, "Order is not open"

            # 标记为已取消
            order.canceled_at = datetime.datetime.utcnow()

            # 处理退款/返还
            if order.amount > 0:  # 买入订单 - 退款
                refund_amount = abs(order.open_shares) * order.limit_price
                account = session.query(Account).filter_by(id=order.account_id).first()
                account.balance += refund_amount
            else:  # 卖出订单 - 返还股票
                self.update_position(order.symbol_name, order.account_id, abs(order.open_shares), session)

            # 设置开放股数为0
            order.open_shares = 0

            return True, None

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
