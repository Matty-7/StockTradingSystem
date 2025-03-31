import threading
import datetime
import logging

logger = logging.getLogger(__name__)

class MatchingEngine:
    def __init__(self, database):
        self.database = database
        self.lock = threading.Lock()
    
    def match_orders(self, new_order):
        """
        Match the new order with existing orders in the order book.
        Returns a list of executed orders.
        """
        logger.info(f"Attempting to match order {new_order.id}: {new_order.amount} shares of {new_order.symbol} at limit {new_order.limit}")
        
        executed_orders = []
        
        # Determine if this is a buy or sell order
        is_buy = new_order.amount > 0
        
        # Get the opposite side orders (sell orders for a buy, buy orders for a sell)
        opposite_orders = self.database.get_orders(new_order.symbol, not is_buy)
        
        if not opposite_orders:
            logger.info(f"No matching orders found for order {new_order.id}")
            return executed_orders
        
        logger.info(f"Found {len(opposite_orders)} potential matching orders")
        
        # Sort orders by price (best price first) and then by time (oldest first)
        # For buy orders, we want to match with sell orders sorted by lowest price
        # For sell orders, we want to match with buy orders sorted by highest price
        if is_buy:
            opposite_orders.sort(key=lambda x: (float(x.limit), x.created_at))
        else:
            opposite_orders.sort(key=lambda x: (-float(x.limit), x.created_at))
        
        remaining_shares = abs(new_order.amount)
        
        for opposite_order in opposite_orders:
            # Check if we still have shares to match
            if remaining_shares <= 0:
                break
            
            # Check price compatibility
            if is_buy:
                price_compatible = float(new_order.limit) >= float(opposite_order.limit)
            else:
                price_compatible = float(new_order.limit) <= float(opposite_order.limit)
            
            if not price_compatible:
                logger.info(f"Price incompatible: new order limit {new_order.limit} vs opposite order limit {opposite_order.limit}")
                continue
            
            # Calculate how many shares can be executed in this match
            opposite_remaining = opposite_order.open_shares
            executable_shares = min(remaining_shares, opposite_remaining)
            
            if executable_shares <= 0:
                continue
            
            logger.info(f"Matching {executable_shares} shares between orders {new_order.id} and {opposite_order.id}")
            
            # Determine execution price (use the price of the order that was open first)
            execution_price = opposite_order.limit if opposite_order.created_at < new_order.created_at else new_order.limit
            logger.info(f"Execution price: {execution_price} (based on older order: {opposite_order.id if opposite_order.created_at < new_order.created_at else new_order.id})")
            
            # Start a database transaction to ensure atomicity
            with self.database.session_scope() as session:
                # Execute the orders
                buyer_id = new_order.account_id if is_buy else opposite_order.account_id
                seller_id = opposite_order.account_id if is_buy else new_order.account_id
                
                # Record execution for the new order
                new_order_execution = self.database.execute_order(
                    new_order.id, 
                    executable_shares, 
                    execution_price,
                    opposite_order.id
                )
                
                # Record execution for the opposite order
                opposite_order_execution = self.database.execute_order(
                    opposite_order.id, 
                    executable_shares, 
                    execution_price,
                    new_order.id
                )
                
                # Update account positions and balances
                # Calculate total value of the transaction
                total_value = float(execution_price) * executable_shares
                
                # Update buyer's position (add shares)
                self.database.update_position(buyer_id, new_order.symbol, executable_shares, session)
                
                # Update seller's balance (add money)
                self.database.update_account_balance(seller_id, total_value, session)
                
                # Update the order objects
                new_order.open_shares -= executable_shares
                opposite_order.open_shares -= executable_shares
                
                logger.info(f"Executed {executable_shares} shares at {execution_price}: " +
                          f"Order {new_order.id} has {new_order.open_shares} open shares, " +
                          f"Order {opposite_order.id} has {opposite_order.open_shares} open shares")
                
                # Record executed transactions for return
                executed_orders.append((new_order_execution, opposite_order_execution))
            
            # Update remaining shares to match
            remaining_shares -= executable_shares
            
            # If the opposite order is fully executed, update its status in the order book
            if opposite_order.open_shares == 0:
                self.database.remove_order(opposite_order.id)
                logger.info(f"Removed fully executed order {opposite_order.id} from order book")
        
        # If new order still has shares to match, add it to the order book
        if new_order.open_shares > 0:
            self.database.add_order(new_order)
            logger.info(f"Added order {new_order.id} with {new_order.open_shares} remaining shares to order book")
        
        return executed_orders
    
    def place_order(self, account_id, symbol, amount, limit_price):
        """Place an order and try to match it"""
        with self.database.session_scope() as session:
            account = session.query(self.database.Account).filter_by(id=account_id).first()
            if not account:
                return False, "Account not found", None
            
            # Buy order, check if balance is sufficient
            if amount > 0:  # Buy
                cost = amount * float(limit_price)
                if account.balance < cost:
                    return False, "Insufficient funds", None
                
                # Deduct balance
                account.balance -= cost
            else:  # Sell
                # Check if shares are sufficient
                position = session.query(self.database.Position).filter_by(
                    account_id=account_id, symbol_name=symbol).first()
                if not position or position.amount < abs(amount):
                    return False, "Insufficient shares", None
                
                # Deduct shares
                position.amount += amount  # amount is negative
            
            # Create order
            order = self.database.create_order(account_id, symbol, amount, limit_price)
            
            # Try to match the order
            self.match_orders(order)
        
        return True, None, order
