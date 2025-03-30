import threading
from decimal import Decimal
import time

class Order:
    """
    Represents a buy or sell order in the exchange system.
    
    An order contains information about the symbol to trade, the amount,
    limit price, and tracks its execution status over time.
    """
    
    def __init__(self, order_id, account_id, symbol, amount, limit_price, creation_time=None):
        """
        Initialize an order
        
        Parameters:
            order_id (int): Unique order identifier
            account_id (str): Account that placed the order
            symbol (str): Symbol to be traded
            amount (float): Amount to buy (positive) or sell (negative)
            limit_price (float): Maximum buy price or minimum sell price
            creation_time (float, optional): Order creation timestamp (seconds since epoch)
        """
        # Validate inputs
        if not isinstance(order_id, int) and not isinstance(order_id, str):
            raise ValueError("Order ID must be an integer or string")
        if not symbol or not isinstance(symbol, str):
            raise ValueError("Symbol must be a non-empty string")
        if amount == 0:
            raise ValueError("Order amount cannot be zero")
        
        self.id = order_id
        self.account_id = str(account_id)
        self.symbol = symbol
        self.amount = float(amount)  # Positive for buy, negative for sell
        self.limit_price = float(limit_price)
        self.time = creation_time or time.time()
        self.open_shares = self.amount  # Initially all shares are open
        self.executions = []  # List of (shares, price, time) tuples
        self.canceled_time = None
        self.lock = threading.Lock()
    
    def is_open(self):
        """Check if order is open"""
        with self.lock:
            return self.open_shares != 0 and self.canceled_time is None
    
    def is_buy(self):
        """Check if this is a buy order"""
        return self.amount > 0
    
    def is_sell(self):
        """Check if this is a sell order"""
        return self.amount < 0
    
    def get_executed_shares(self):
        """Get the total number of shares that have been executed"""
        with self.lock:
            return sum(shares for shares, _, _ in self.executions)
    
    def get_remaining_shares(self):
        """Get the number of shares remaining to be executed"""
        with self.lock:
            return abs(self.open_shares)
    
    def is_price_compatible(self, other_order):
        """
        Check if this order's price is compatible with another order
        
        For orders to be compatible, the buy price must be >= sell price
        
        Parameters:
            other_order (Order): The order to check compatibility with
            
        Returns:
            bool: True if prices are compatible, False otherwise
        """
        # One must be buy and the other sell
        if (self.is_buy() and other_order.is_buy()) or (self.is_sell() and other_order.is_sell()):
            return False
            
        # If this is buy and other is sell
        if self.is_buy():
            return self.limit_price >= other_order.limit_price
        # If this is sell and other is buy
        else:
            return other_order.limit_price >= self.limit_price
    
    def determine_execution_price(self, other_order):
        """
        Determine the execution price between this order and another order
        
        According to the requirements, the execution price should be the price
        of the order that was open first.
        
        Parameters:
            other_order (Order): The matching order
            
        Returns:
            float: The execution price
        """
        # The price of the order that was open first
        if self.time <= other_order.time:
            return self.limit_price
        else:
            return other_order.limit_price
    
    def execute(self, shares, price, execution_time=None):
        """
        Execute part of the order
        
        Parameters:
            shares (float): Number of shares to execute
            price (float): Execution price
            execution_time (float, optional): Timestamp for execution
            
        Returns:
            bool: Whether execution was successful
        """
        with self.lock:
            if self.canceled_time is not None:
                return False
            
            # Cap shares at available open shares
            execute_shares = min(abs(shares), abs(self.open_shares))
            if execute_shares <= 0:
                return False
            
            # Update open shares
            if self.amount > 0:  # Buy
                self.open_shares -= execute_shares
            else:  # Sell
                self.open_shares += execute_shares
            
            # Record execution
            current_time = execution_time or time.time()
            self.executions.append((execute_shares, price, current_time))
            return True
    
    def cancel(self, cancel_time=None):
        """
        Cancel the order
        
        Parameters:
            cancel_time (float, optional): Timestamp for cancellation
            
        Returns:
            bool: Whether cancellation was successful
        """
        with self.lock:
            if not self.is_open():
                return False
                
            self.canceled_time = cancel_time or time.time()
            self.open_shares = 0
            return True
    
    def get_refund_amount(self):
        """
        Calculate refund amount for cancelling a buy order
        
        Returns:
            float: Amount to be refunded
        """
        with self.lock:
            if self.is_buy():
                return abs(self.open_shares) * self.limit_price
            return 0
    
    def get_return_shares(self):
        """
        Calculate shares to return when cancelling a sell order
        
        Returns:
            float: Shares to be returned
        """
        with self.lock:
            if self.is_sell():
                return abs(self.open_shares)
            return 0
    
    def get_status(self):
        """
        Get order status for XML response
        
        Returns:
            list: XML elements representing order status
        """
        with self.lock:
            result = []
            
            # Add open status if open
            if self.open_shares != 0 and self.canceled_time is None:
                result.append(f'<open shares="{abs(self.open_shares)}"/>')
            
            # Add canceled status if canceled
            if self.canceled_time is not None:
                result.append(f'<canceled shares="{abs(self.amount) - sum(e[0] for e in self.executions)}" time="{int(self.canceled_time)}"/>')
            
            # Add execution statuses
            for shares, price, execution_time in self.executions:
                result.append(f'<executed shares="{shares}" price="{price}" time="{int(execution_time)}"/>')
            
            return result
    
    def to_dict(self):
        """
        Convert order to dictionary format for API response or serialization
        
        Returns:
            dict: Order information dictionary
        """
        with self.lock:
            executions_list = [
                {"shares": shares, "price": price, "time": execution_time}
                for shares, price, execution_time in self.executions
            ]
            
            return {
                "id": self.id,
                "account_id": self.account_id,
                "symbol": self.symbol,
                "amount": self.amount,
                "limit_price": self.limit_price,
                "time": self.time,
                "open_shares": self.open_shares,
                "executions": executions_list,
                "canceled_time": self.canceled_time,
                "is_open": self.is_open()
            }
