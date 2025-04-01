import threading
import datetime
import logging
# Import Account and Position models (assuming they are in database.py)
from database import Account, Position, Order

# Setup logger for this module
logger = logging.getLogger(__name__)
# logger.setLevel(logging.DEBUG) # Set level if needed

class MatchingEngine:
    def __init__(self, database):
        self.database = database
        self.lock = threading.Lock()
        self.logger = logging.getLogger(__name__)

    def match_orders(self, new_order, session):
        """
        Match the new order with existing orders in the order book.
        Returns a list of executed orders.
        """
        session.add(new_order)
        logger.info(f"Attempting to match order {new_order.id}: {new_order.amount} shares of {new_order.symbol_name} at limit {new_order.limit_price}")

        executed_orders = []

        # Determine if this is a buy or sell order
        is_buy = new_order.amount > 0

        # Get the opposite side orders (sell orders for a buy, buy orders for a sell)
        # opposite_orders = self.database.get_orders(new_order.symbol, not is_buy)
        if is_buy:
            opposite_orders = self.database.get_sell_orders(new_order.symbol_name)
        else:
            opposite_orders = self.database.get_buy_orders(new_order.symbol_name)

        session.add(new_order)
        if not opposite_orders:
            logger.info(f"No matching orders found for order {new_order.id}")
            return executed_orders

        logger.info(f"Found {len(opposite_orders)} potential matching orders")

        for order in opposite_orders:
            session.add(order)

        # Sort orders by price (best price first) and then by time (oldest first)
        # For buy orders, we want to match with sell orders sorted by lowest price
        # For sell orders, we want to match with buy orders sorted by highest price
        if is_buy:
            opposite_orders.sort(key=lambda x: (float(x.limit_price), x.created_at))
        else:
            opposite_orders.sort(key=lambda x: (-float(x.limit_price), x.created_at))
        session.add(new_order)
        # Use open_shares as it reflects the current state
        remaining_shares = abs(new_order.open_shares)

        for opposite_order in opposite_orders:
            # Check if we still have shares to match
            if remaining_shares <= 0:
                break

            # Check price compatibility
            if is_buy:
                price_compatible = float(new_order.limit_price) >= float(opposite_order.limit_price)
            else:
                price_compatible = float(new_order.limit_price) <= float(opposite_order.limit_price)

            if not price_compatible:
                logger.info(f"Price incompatible: new order limit {new_order.limit_price} vs opposite order limit {opposite_order.limit_price}")
                continue

            # Calculate how many shares can be executed in this match
            opposite_remaining = abs(opposite_order.open_shares) # Use absolute value
            executable_shares = min(remaining_shares, opposite_remaining)

            if executable_shares <= 0:
                continue

            logger.info(f"Matching {executable_shares} shares between orders {new_order.id} and {opposite_order.id}")

            # Determine execution price (use the price of the order that was open first)
            execution_price = opposite_order.limit_price if opposite_order.created_at < new_order.created_at else new_order.limit_price
            logger.info(f"Execution price: {execution_price} (based on older order: {opposite_order.id if opposite_order.created_at < new_order.created_at else new_order.id})")

            # Start a database transaction to ensure atomicity
            #with self.database.session_scope() as session:
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

            # Note: execute_order_part already updates open_shares for both orders

            logger.info(f"Executed {executable_shares} shares at {execution_price}: " +
                        f"Order {new_order.id} has {new_order.open_shares} open shares, " +
                        f"Order {opposite_order.id} has {opposite_order.open_shares} open shares")

            # Record executed transactions for return
            executed_orders.append((new_order_execution, opposite_order_execution))

            # Update remaining shares to match
            remaining_shares -= executable_shares

            # If the opposite order is fully executed, update its status in the order book
            if opposite_order.open_shares == 0:
                # No explicit removal needed, query filters handle it
                logger.info(f"Removed fully executed order {opposite_order.id} from order book")

        session.add(new_order)
        # If new order still has shares to match, add it to the order book
        if new_order.open_shares != 0: # Check against 0, works for both buy/sell
            # No explicit add needed, session commit handles persistence
            logger.info(f"Order {new_order.id} with {new_order.open_shares} remaining shares remains open")

        return executed_orders

    def place_order(self, account_id, symbol, amount, limit_price):
        """Place an order and try to match it"""
        order_id = None # Initialize order_id
        success = False
        error_msg = None

        # Acquire lock before starting the order placement and matching process
        with self.lock:
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
                        if account.balance < cost:
                            error_msg = "Insufficient funds"
                            return success, error_msg, order_id # Return False, msg, None

                        # Deduct balance (optimistically, within transaction)
                        self.logger.info(f"Deducting {cost} from account {account_id} for potential buy order")
                        account.balance -= cost
                        session.add(account)
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
                        session.add(position)

                    # Create order
                    order = self.database.create_order(account_id, symbol, amount, limit_price)
                    session.add(order)
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
