import threading
from decimal import Decimal

class Account:
    """
    Account class: Manages exchange user account information, including balance and positions
    
    Attributes:
        id (str): Unique account identifier
        balance (Decimal): Account balance (in USD)
        positions (dict): Holding information {symbol: amount}
        lock (threading.Lock): Thread lock, ensuring thread safety for account operations
    """
    
    def __init__(self, account_id, balance):
        """
        Initialize account
        
        Parameters:
            account_id (str): Unique account identifier
            balance (float/str/Decimal): Initial balance
        """
        # Validate account ID format
        if not account_id or not str(account_id).isdigit():
            raise ValueError("Account ID must be a sequence of one or more base-10 digits")
        
        self.id = str(account_id)  # Ensure string type
        self.balance = Decimal(str(balance))  # Use Decimal type for precise calculation
        self.positions = {}  # symbol -> amount
        self.lock = threading.Lock()
        
        # Validate if initial balance is positive
        if self.balance < 0:
            raise ValueError("Initial balance cannot be negative")
    
    def get_balance(self):
        """Get current balance"""
        with self.lock:
            return float(self.balance)
    
    def update_balance(self, amount):
        """
        Update balance
        
        Parameters:
            amount (float/str/Decimal): Amount to change (positive for increase, negative for decrease)
            
        Returns:
            bool: Whether the operation was successful
            float: Updated balance
        """
        with self.lock:
            amount_decimal = Decimal(str(amount))
            new_balance = self.balance + amount_decimal
            
            # Check if balance would become negative
            if new_balance < 0:
                return False, float(self.balance)
            
            self.balance = new_balance
            return True, float(self.balance)
    
    def has_sufficient_balance(self, amount):
        """
        Check if account has sufficient balance
        
        Parameters:
            amount (float/str/Decimal): Required amount
            
        Returns:
            bool: Whether there is sufficient balance
        """
        with self.lock:
            return self.balance >= Decimal(str(amount))
    
    def get_position(self, symbol):
        """
        Get the position amount for a specific symbol
        
        Parameters:
            symbol (str): Stock symbol
            
        Returns:
            float: Position amount (returns 0 if none exists)
        """
        with self.lock:
            return float(self.positions.get(symbol, 0))
    
    def update_position(self, symbol, amount):
        """
        Update stock position
        
        Parameters:
            symbol (str): Stock symbol
            amount (float/str/Decimal): Amount to change (positive for increase, negative for decrease)
            
        Returns:
            bool: Whether the operation was successful
            float: Updated position amount
        """
        with self.lock:
            amount_decimal = Decimal(str(amount))
            current = self.positions.get(symbol, Decimal('0'))
            new_position = current + amount_decimal
            
            # Check if position would become negative (short selling not allowed)
            if new_position < 0:
                return False, float(current)
            
            self.positions[symbol] = new_position
            return True, float(new_position)
    
    def add_position(self, symbol, amount):
        """
        Add new position or increase existing position
        
        Parameters:
            symbol (str): Stock symbol
            amount (float/str/Decimal): Position amount
            
        Returns:
            float: Updated position amount
        """
        with self.lock:
            amount_decimal = Decimal(str(amount))
            if amount_decimal <= 0:
                raise ValueError("Position amount must be positive")
                
            if symbol in self.positions:
                self.positions[symbol] += amount_decimal
            else:
                self.positions[symbol] = amount_decimal
                
            return float(self.positions[symbol])
    
    def has_sufficient_shares(self, symbol, amount):
        """
        Check if there are enough shares to sell
        
        Parameters:
            symbol (str): Stock symbol
            amount (float/str/Decimal): Amount needed to sell
            
        Returns:
            bool: Whether there are sufficient shares
        """
        with self.lock:
            amount_decimal = Decimal(str(amount))
            return symbol in self.positions and self.positions[symbol] >= amount_decimal
    
    def place_buy_order(self, symbol, amount, price):
        """
        Create buy order, deduct corresponding funds
        
        Parameters:
            symbol (str): Stock symbol
            amount (float/str/Decimal): Buy amount
            price (float/str/Decimal): Limit price
            
        Returns:
            bool: Whether the operation was successful
            str: Error message (if any)
        """
        with self.lock:
            amount_decimal = Decimal(str(amount))
            price_decimal = Decimal(str(price))
            total_cost = amount_decimal * price_decimal
            
            # Check if balance is sufficient
            if self.balance < total_cost:
                return False, "Insufficient funds"
            
            # Deduct funds
            self.balance -= total_cost
            return True, None
    
    def place_sell_order(self, symbol, amount):
        """
        Create sell order, deduct corresponding shares
        
        Parameters:
            symbol (str): Stock symbol
            amount (float/str/Decimal): Sell amount (positive)
            
        Returns:
            bool: Whether the operation was successful
            str: Error message (if any)
        """
        with self.lock:
            amount_decimal = Decimal(str(amount))
            
            # Check if position is sufficient
            if symbol not in self.positions or self.positions[symbol] < amount_decimal:
                return False, "Insufficient shares"
            
            # Deduct shares
            self.positions[symbol] -= amount_decimal
            return True, None
    
    def cancel_buy_order(self, amount, price):
        """
        Cancel buy order, refund funds
        
        Parameters:
            amount (float/str/Decimal): Buy amount to cancel
            price (float/str/Decimal): Buy limit price
            
        Returns:
            bool: Whether the operation was successful
        """
        with self.lock:
            amount_decimal = Decimal(str(amount))
            price_decimal = Decimal(str(price))
            refund = amount_decimal * price_decimal
            
            self.balance += refund
            return True
    
    def cancel_sell_order(self, symbol, amount):
        """
        Cancel sell order, return shares
        
        Parameters:
            symbol (str): Stock symbol
            amount (float/str/Decimal): Sell amount to cancel
            
        Returns:
            bool: Whether the operation was successful
        """
        with self.lock:
            amount_decimal = Decimal(str(amount))
            
            if symbol in self.positions:
                self.positions[symbol] += amount_decimal
            else:
                self.positions[symbol] = amount_decimal
                
            return True
    
    def execute_buy(self, symbol, amount, price):
        """
        Execute buy order, increase position
        
        Parameters:
            symbol (str): Stock symbol
            amount (float/str/Decimal): Buy amount
            price (float/str/Decimal): Execution price
            
        Returns:
            bool: Whether the operation was successful
        """
        with self.lock:
            amount_decimal = Decimal(str(amount))
            
            # Increase position
            if symbol in self.positions:
                self.positions[symbol] += amount_decimal
            else:
                self.positions[symbol] = amount_decimal
                
            return True
    
    def execute_sell(self, symbol, amount, price):
        """
        Execute sell order, increase funds
        
        Parameters:
            symbol (str): Stock symbol
            amount (float/str/Decimal): Sell amount
            price (float/str/Decimal): Execution price
            
        Returns:
            bool: Whether the operation was successful
        """
        with self.lock:
            amount_decimal = Decimal(str(amount))
            price_decimal = Decimal(str(price))
            credit = amount_decimal * price_decimal
            
            # Increase funds
            self.balance += credit
            return True
    
    def to_dict(self):
        """
        Convert account to dictionary format for API response or serialization
        
        Returns:
            dict: Account information dictionary
        """
        with self.lock:
            positions_dict = {symbol: float(amount) for symbol, amount in self.positions.items()}
            return {
                'id': self.id,
                'balance': float(self.balance),
                'positions': positions_dict
            }
