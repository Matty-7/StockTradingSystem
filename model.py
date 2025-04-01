from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, DateTime, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
import datetime

Base = declarative_base()

class Account(Base):
    __tablename__ = 'accounts'

    id = Column(String, primary_key=True)
    balance = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationship
    positions = relationship("Position", back_populates="account")
    orders = relationship("Order", back_populates="account")

    def __repr__(self):
        return f"<Account(id='{self.id}', balance={self.balance})>"

class Symbol(Base):
    __tablename__ = 'symbols'

    name = Column(String, primary_key=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationship
    positions = relationship("Position", back_populates="symbol")
    orders = relationship("Order", back_populates="symbol")

    def __repr__(self):
        return f"<Symbol(name='{self.name}')>"

class Position(Base):
    __tablename__ = 'positions'

    id = Column(Integer, primary_key=True)
    account_id = Column(String, ForeignKey('accounts.id'), nullable=False)
    symbol_name = Column(String, ForeignKey('symbols.name'), nullable=False)
    amount = Column(Float, nullable=False, default=0.0)

    # Relationship
    account = relationship("Account", back_populates="positions")
    symbol = relationship("Symbol", back_populates="positions")

    __table_args__ = (
        # UniqueConstraint('account_id', 'symbol_name', name='_account_symbol_uc'),
    )

    def __repr__(self):
        return f"<Position(account_id='{self.account_id}', symbol='{self.symbol_name}', amount={self.amount})>"

class Order(Base):
    __tablename__ = 'orders'

    id = Column(Integer, primary_key=True)
    account_id = Column(String, ForeignKey('accounts.id'), nullable=False)
    symbol_name = Column(String, ForeignKey('symbols.name'), nullable=False)
    amount = Column(Float, nullable=False)  # Positive for buy, negative for sell
    limit_price = Column(Float, nullable=False)
    open_shares = Column(Float, nullable=False)  # Unexecuted shares
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    canceled_at = Column(DateTime, nullable=True)  # Cancel time, if empty then not canceled

    # Relationship
    account = relationship("Account", back_populates="orders")
    symbol = relationship("Symbol", back_populates="orders")
    executions = relationship("Execution", back_populates="order")

    def __repr__(self):
        return f"<Order(id={self.id}, account_id='{self.account_id}', symbol='{self.symbol_name}', amount={self.amount}, limit_price={self.limit_price})>"

    def get_status(self):
        """
        Get order status for XML response

        Returns:
            list: XML elements representing order status
        """
        result = []

        # Add open status if open
        if self.open_shares != 0 and self.canceled_at is None:
            result.append(f'<open shares="{abs(self.open_shares)}"/>')

        # Add canceled status if canceled
        if self.canceled_at is not None:
            result.append(f'<canceled shares="{abs(self.amount) - sum(e[0] for e in self.executions)}" time="{int(self.canceled_at.timestamp())}"/>')

        # Add execution statuses
        for execution in self.executions:
            result.append(f'<executed shares="{execution.shares}" price="{execution.price}" time="{int(execution.execution_time.timestamp())}"/>')

        return result

class Execution(Base):
    __tablename__ = 'executions'

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey('orders.id'), nullable=False)
    shares = Column(Float, nullable=False)
    price = Column(Float, nullable=False)
    executed_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationship
    order = relationship("Order", back_populates="executions")

    def __repr__(self):
        return f"<Execution(order_id={self.order_id}, shares={self.shares}, price={self.price})>"

def init_db(db_url):
    """Initialize the database: create all tables"""
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    return engine


def reset_db(db_url):
    """Reset the database: drop all tables and recreate them."""
    engine = create_engine(db_url)

    # Drop all tables
    Base.metadata.drop_all(engine)

    # Create all tables
    Base.metadata.create_all(engine)

    return engine
