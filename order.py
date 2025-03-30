import threading

class Order:
    def __init__(self, order_id, account_id, symbol, amount, limit_price, time):
        self.id = order_id
        self.account_id = account_id
        self.symbol = symbol
        self.amount = amount  # Positive for buy, negative for sell
        self.limit_price = float(limit_price)
        self.time = time
        self.open_shares = amount  # Initially all shares are open
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
    
    def execute(self, shares, price, time):
        """Execute part of the order"""
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
            self.executions.append((execute_shares, price, time))
            return True
    
    def cancel(self, time):
        """Cancel the order"""
        with self.lock:
            self.canceled_time = time
            self.open_shares = 0
    
    def get_status(self):
        """Get order status for XML response"""
        with self.lock:
            result = []
            
            # Add open status if open
            if self.open_shares != 0 and self.canceled_time is None:
                result.append(f'<open shares="{abs(self.open_shares)}"/>')
            
            # Add canceled status if canceled
            if self.canceled_time is not None:
                result.append(f'<canceled shares="{abs(self.amount) - sum(e[0] for e in self.executions)}" time="{int(self.canceled_time)}"/>')
            
            # Add execution statuses
            for shares, price, time in self.executions:
                result.append(f'<executed shares="{shares}" price="{price}" time="{int(time)}"/>')
            
            return result
