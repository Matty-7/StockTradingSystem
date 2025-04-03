import threading
import datetime
import logging
from database import Account, Position, Order
import heapq
from collections import defaultdict

logger = logging.getLogger(__name__)

class MatchingEngine:
    def __init__(self, database):
        self.database = database
        # Replace global lock with symbol-based locks for finer granularity
        self.symbol_locks = defaultdict(threading.Lock)
        # In-memory order books using priority queues
        self.buy_orders = defaultdict(list)  # Symbol -> list of (-price, time, order_id)
        self.sell_orders = defaultdict(list)  # Symbol -> list of (price, time, order_id)
        self.logger = logging.getLogger(__name__)
    
    def get_symbol_lock(self, symbol):
        """Get the lock for a specific symbol"""
        return self.symbol_locks[symbol]
        
    def add_to_orderbook(self, order, session):
        """Add an order to the in-memory order book"""
        symbol = order.symbol_name
        order_id = order.id
        price = float(order.limit_price)
        timestamp = order.created_at.timestamp()
        
        if order.amount > 0:  # Buy order
            # Use negative price for max heap behavior
            heapq.heappush(self.buy_orders[symbol], (-price, timestamp, order_id))
            self.logger.info(f"Added buy order {order_id} to order book for {symbol} at price {price}")
        else:  # Sell order
            heapq.heappush(self.sell_orders[symbol], (price, timestamp, order_id))
            self.logger.info(f"Added sell order {order_id} to order book for {symbol} at price {price}")
    
    def remove_from_orderbook(self, order_id, symbol, is_buy):
        """Remove an order from the in-memory order book"""
        if is_buy:
            # Filter out the specified order
            self.buy_orders[symbol] = [o for o in self.buy_orders[symbol] if o[2] != order_id]
            # Restore heap property
            heapq.heapify(self.buy_orders[symbol])
        else:
            # Filter out the specified order
            self.sell_orders[symbol] = [o for o in self.sell_orders[symbol] if o[2] != order_id]
            # Restore heap property
            heapq.heapify(self.sell_orders[symbol])
    
    def match_orders(self, new_order, session):
        """
        Match the new order with existing orders in the order book.
        Returns a list of executed orders.
        """
        session.add(new_order)
        symbol = new_order.symbol_name
        logger.info(f"Attempting to match order {new_order.id}: {new_order.amount} shares of {symbol} at limit {new_order.limit_price}")

        executed_orders = []

        # Determine if this is a buy or sell order
        is_buy = new_order.amount > 0
        
        # Get matching orders from our in-memory order book
        if is_buy:
            # For buy orders, match with sell orders (lowest price first)
            matching_orders = self.sell_orders[symbol]
        else:
            # For sell orders, match with buy orders (highest price first)
            matching_orders = self.buy_orders[symbol]
            
        # No matching orders in memory
        if not matching_orders:
            # Add this order to our in-memory book and database
            self.add_to_orderbook(new_order, session)
            logger.info(f"No matching orders found for order {new_order.id}")
            return executed_orders

        logger.info(f"Found {len(matching_orders)} potential matching orders in memory")
        
        # Use open_shares as it reflects the current state
        remaining_shares = abs(new_order.open_shares)
        matched_order_ids = []
        
        # Process the heap without fully destructing it
        temp_heap = matching_orders.copy()
        
        while temp_heap and remaining_shares > 0:
            # Get best price (lowest sell or highest buy)
            if is_buy:
                price_tuple = heapq.heappop(temp_heap)
                price = price_tuple[0]  # Already positive for sell orders
                opposite_order_id = price_tuple[2]
            else:
                price_tuple = heapq.heappop(temp_heap)
                price = -price_tuple[0]  # Convert back from negative for buy orders
                opposite_order_id = price_tuple[2]
            
            # Retrieve the opposite order from database
            opposite_order = self.database.get_order(opposite_order_id, session)
            if not opposite_order or opposite_order.open_shares == 0 or opposite_order.canceled_at is not None:
                # Skip invalid or closed orders
                self.remove_from_orderbook(opposite_order_id, symbol, not is_buy)
                continue
                
            # Check price compatibility
            new_price = float(new_order.limit_price)
            opposite_price = float(opposite_order.limit_price)
            
            if is_buy:
                price_compatible = new_price >= opposite_price
            else:
                price_compatible = new_price <= opposite_price
                
            if not price_compatible:
                logger.info(f"Price incompatible: new order limit {new_price} vs opposite order limit {opposite_price}")
                # Put back the incompatible order and stop looking
                # We won't find better prices in the sorted heap
                break

            # Calculate how many shares can be executed in this match
            opposite_remaining = abs(opposite_order.open_shares)
            executable_shares = min(remaining_shares, opposite_remaining)

            if executable_shares <= 0:
                continue

            logger.info(f"Matching {executable_shares} shares between orders {new_order.id} and {opposite_order.id}")

            # Determine execution price (use the price of the order that was open first)
            execution_price = opposite_order.limit_price if opposite_order.created_at < new_order.created_at else new_order.limit_price
            logger.info(f"Execution price: {execution_price}")

            # Execute the orders
            buyer_id = new_order.account_id if is_buy else opposite_order.account_id
            seller_id = opposite_order.account_id if is_buy else new_order.account_id

            # Record execution for the new order
            new_order_execution = self.database.execute_order_part(
                new_order,
                executable_shares,
                execution_price,
                session
            )

            # Record execution for the opposite order
            opposite_order_execution = self.database.execute_order_part(
                opposite_order,
                executable_shares,
                execution_price,
                session
            )

            # Update account positions and balances
            # Calculate total value of the transaction
            total_value = float(execution_price) * executable_shares

            # Update buyer's position (add shares)
            self.database.update_position(buyer_id, new_order.symbol_name, executable_shares, session)

            # Update seller's balance (add money)
            self.database.update_account_balance(seller_id, total_value, session)

            logger.info(f"Executed {executable_shares} shares at {execution_price}: " +
                        f"Order {new_order.id} has {new_order.open_shares} open shares, " +
                        f"Order {opposite_order.id} has {opposite_order.open_shares} open shares")

            # Record executed transactions for return
            executed_orders.append((new_order_execution, opposite_order_execution))

            # Update remaining shares to match
            remaining_shares -= executable_shares
            
            # If the opposite order is fully executed, remove it from memory
            if opposite_order.open_shares == 0:
                matched_order_ids.append(opposite_order_id)
                logger.info(f"Order {opposite_order_id} fully executed, removing from order book")
        
        # Remove fully matched orders from our in-memory book
        for order_id in matched_order_ids:
            self.remove_from_orderbook(order_id, symbol, not is_buy)
        
        # If new order still has shares to match, add it to the order book
        if new_order.open_shares != 0:
            self.add_to_orderbook(new_order, session)
            logger.info(f"Order {new_order.id} with {new_order.open_shares} remaining shares remains open")

        return executed_orders

    def place_order(self, account_id, symbol, amount, limit_price):
        """Place an order and try to match it"""
        order_id = None # Initialize order_id
        success = False
        error_msg = None

        # Use symbol-specific lock instead of global lock
        with self.get_symbol_lock(symbol):
            try:
                with self.database.session_scope() as session:
                    # Use the imported Account model directly
                    account = session.query(Account).filter_by(id=account_id).with_for_update().first()
                    if not account:
                        error_msg = "Account not found"
                        return success, error_msg, order_id # Return False, msg, None

                    # Buy order, check if balance is sufficient
                    if amount > 0:  # Buy
                        cost = amount * float(limit_price)
                        # Allow order if balance is exactly equal to cost or greater
                        if account.balance < cost:
                            error_msg = "Insufficient funds"
                            return success, error_msg, order_id # Return False, msg, None

                        # Deduct balance (optimistically, within transaction)
                        self.logger.info(f"Deducting {cost} from account {account_id} for potential buy order")
                        account.balance -= cost
                    else:  # Sell
                        # Check if shares are sufficient
                        # Use the imported Position model directly
                        position = session.query(Position).filter_by(
                            account_id=account_id, symbol_name=symbol).with_for_update().first()
                        if not position or position.amount < abs(amount):
                            error_msg = "Insufficient shares"
                            return success, error_msg, order_id # Return False, msg, None

                        # Deduct shares (optimistically, within transaction)
                        self.logger.info(f"Deducting {abs(amount)} shares of {symbol} from account {account_id} for potential sell order")
                        position.amount += amount  # amount is negative

                    # Create order
                    order = self.database.create_order(account_id, symbol, amount, limit_price, session)
                    session.flush() # Flush to get the order ID before matching
                    order_id = order.id
                    self.logger.info(f"Created order {order_id}. Attempting match.")

                    # Try to match the order within the same transaction
                    self.match_orders(order, session)

                    # If we reached here without exceptions, the DB transaction will commit
                    success = True
                    self.logger.info(f"Order {order_id} placed and matched successfully (or added to book).")

            except Exception as e:
                # Log the exception that occurred within the transaction scope
                self.logger.exception(f"Error during place_order for account {account_id}, symbol {symbol}: {e}")
                error_msg = f"Internal server error during order placement: {str(e)}"
                # success remains False, order_id might be None or the generated ID
                # The transaction will be rolled back by session_scope

        # Return the final status outside the lock and session scope
        return success, error_msg, order_id
