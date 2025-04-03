import xml.etree.ElementTree as ET
import time
import datetime
import logging
import re
from model import Account, Position, Order, Execution
import threading
import traceback

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

class XMLHandler:
    def __init__(self, database, matching_engine):
        self.database = database
        self.matching_engine = matching_engine

    def process_request(self, xml_data):
        """Process XML request and return XML response"""
        logger.debug(f"Received XML data: {xml_data[:500]}...") # Log received data (truncated)
        try:
            root = ET.fromstring(xml_data)
            request_type = root.tag
            logger.info(f"Processing {request_type} request")

            if request_type == 'create':
                return self.handle_create(root)
            elif request_type == 'transactions':
                return self.handle_transactions(root)
            else:
                logger.warning(f"Unknown request type: {request_type}")
                return f'<results><error>Unknown request type: {request_type}</error></results>'
        except ET.ParseError as e:
            logger.error(f"XML parse error: {e} for data: {xml_data[:200]}...")
            return '<results><error>Invalid XML format</error></results>'
        except Exception as e:
            logger.exception(f"Unexpected error processing request: {xml_data[:200]}...") # Log exception info
            return f'<results><error>Internal server error: {str(e)}</error></results>'

    def handle_create(self, root):
        """Handle create requests"""
        results_root = ET.Element('results')
        logger.info("Handling create request") # Use logger

        for child in root:
            if child.tag == 'account':
                account_id = child.attrib.get('id')
                balance = child.attrib.get('balance')
                if account_id is None or balance is None:
                     logger.warning("Create account missing id or balance") # Use logger
                     # Add error element
                     continue
                success, error = self.database.create_account(account_id, float(balance))
                if success:
                    created = ET.SubElement(results_root, 'created')
                    created.set('id', account_id)
                else:
                    error_elem = ET.SubElement(results_root, 'error')
                    error_elem.set('id', account_id)
                    error_elem.text = error

            elif child.tag == 'symbol':
                symbol = child.attrib.get('sym')
                if child.attrib.get('sym') is None:
                     logger.warning("Create symbol missing sym attribute") # Use logger
                     # Add error element
                     continue
                for account_elem in child:
                    if account_elem.tag == 'account':
                        account_id = account_elem.attrib.get('id')
                        amount = float(account_elem.text)

                        success, error = self.database.create_symbol(symbol, account_id, amount)
                        if success:
                            created = ET.SubElement(results_root, 'created')
                            created.set('sym', symbol)
                            created.set('id', account_id)
                        else:
                            error_elem = ET.SubElement(results_root, 'error')
                            error_elem.set('sym', symbol)
                            error_elem.set('id', account_id)
                            error_elem.text = error

        logger.debug("Finished handling create request") # Use logger
        return ET.tostring(results_root, encoding='utf-8').decode('utf-8')

    def handle_transactions(self, root):
        """Handle transaction requests"""
        account_id = root.attrib.get('id')
        if not account_id:
            logger.warning("Transactions request missing account ID")
            return '<results><error>Missing account ID in transactions tag</error></results>'

        logger.info(f"Handling transactions for account ID: {account_id}")
        results_root = ET.Element('results')

        # Validate account existence once
        account = self.database.get_account(account_id)
        if not account:
            logger.warning(f"Account ID {account_id} not found. Failing all transactions.")
            # Return error for each child transaction as per spec
            for i, child in enumerate(root):
                elem_name = child.tag
                attrs = child.attrib
                error_attrs = attrs.copy()
                error_attrs['error'] = f"Account {account_id} not found"
                logger.debug(f"Adding account not found error for child {i} ({elem_name})")
                results_root.append(ET.Element('error', error_attrs))
            return ET.tostring(results_root, encoding='utf-8').decode('utf-8')

        # Process each child transaction
        for i, child in enumerate(root):
            elem_name = child.tag
            attrs = child.attrib
            logger.info(f"Processing transaction {i+1}: {elem_name} with attributes {attrs}")

            if elem_name == 'order':
                # Split order processing into a separate method
                self._process_order(child, account_id, results_root)
            elif elem_name == 'query':
                # Split query processing into a separate method
                self._process_query(child, account_id, results_root)
            elif elem_name == 'cancel':
                # Split cancel processing into a separate method
                self._process_cancel(child, account_id, results_root)
            else:
                logger.warning(f"Unknown transaction type '{elem_name}' in request for account {account_id}")
                results_root.append(ET.Element('error', {'type': elem_name, 'error': f"Unknown transaction type: {elem_name}"}))

        response_str = ET.tostring(results_root, encoding='utf-8').decode('utf-8')
        logger.debug(f"Sending response for account {account_id}: {response_str[:500]}...")
        return response_str
        
    def _process_order(self, order_elem, account_id, results_root):
        """Process an order transaction"""
        attrs = order_elem.attrib
        sym = attrs.get('sym')
        amount_str = attrs.get('amount')
        limit_str = attrs.get('limit')

        # Check for missing required attributes
        if sym is None or amount_str is None or limit_str is None:
            error_text = "Order tag missing required attributes (sym, amount, or limit)"
            logger.warning(f"{error_text} in request for account {account_id}")
            err_attrs = {k: v for k, v in attrs.items() if v is not None} # Include present attributes
            err_attrs['error'] = error_text
            results_root.append(ET.Element('error', err_attrs))
            return

        try:
            amount_val = float(amount_str)
            limit_val = float(limit_str)
        except ValueError:
            error_text = "Invalid numeric value for amount or limit"
            logger.warning(f"{error_text} (amount='{amount_str}', limit='{limit_str}') for account {account_id}")
            err_attrs = attrs.copy()
            err_attrs['error'] = error_text
            results_root.append(ET.Element('error', err_attrs))
            return

        # Call matching engine
        try:
            success, error_msg, order_id = self.matching_engine.place_order(account_id, sym, amount_val, limit_val)
            if success:
                logger.info(f"Order placed successfully for account {account_id}, sym {sym}. Order ID: {order_id}")
                results_root.append(ET.Element('opened', {
                    'sym': sym,
                    'amount': amount_str,
                    'limit': limit_str,
                    'id': str(order_id)
                }))
            else:
                logger.warning(f"Order placement failed for account {account_id}, sym {sym}: {error_msg}")
                results_root.append(ET.Element('error', {
                    'sym': sym,
                    'amount': amount_str,
                    'limit': limit_str,
                    'error': str(error_msg) # Include specific error from engine
                }))
        except Exception as e:
            logger.exception(f"Unexpected error during place_order call for account {account_id}")
            results_root.append(ET.Element('error', {
                'sym': sym,
                'amount': amount_str,
                'limit': limit_str,
                'error': f'Internal server error during order processing: {e}'
            }))
    
    def _process_query(self, query_elem, account_id, results_root):
        """Process a query transaction"""
        attrs = query_elem.attrib
        trans_id = attrs.get('id')
        
        if not trans_id:
            logger.warning(f"Query tag missing id attribute for account {account_id}")
            results_root.append(ET.Element('error', {'error': "Query tag missing id attribute"}))
            return
            
        try:
            order_id = int(trans_id)
            logger.info(f"Querying status for order ID: {order_id} (Account: {account_id})")

            status_element = None
            error_element = None

            # Use a session scope for all database operations
            with self.database.session_scope() as session:
                # First, check if the order exists and belongs to the user
                order_check = session.query(Order).filter_by(id=order_id).first()

                if not order_check:
                    logger.warning(f"Query failed: Order ID {order_id} not found (Account: {account_id})")
                    error_element = ET.Element('error', {'id': trans_id, 'error': "Order not found"})
                # Check if the order belongs to the requesting account
                elif order_check.account_id != account_id:
                    logger.warning(f"Account {account_id} attempted to query order {order_id} belonging to account {order_check.account_id}")
                    error_element = ET.Element('error', {'id': trans_id, 'error': "Permission denied: Order belongs to another account"})
                else:
                    # Order exists and permission granted, now get the detailed status
                    try:
                        # Capture ALL data needed from the order within the session
                        order_id = order_check.id
                        order_account_id = order_check.account_id
                        order_symbol = order_check.symbol_name
                        order_amount = order_check.amount
                        order_limit_price = float(order_check.limit_price)
                        order_created_at = order_check.created_at.isoformat() if order_check.created_at else None
                        order_open_shares = order_check.open_shares
                        order_is_canceled = order_check.canceled_at is not None
                        order_canceled_at = order_check.canceled_at.isoformat() if order_check.canceled_at else None

                        # Get all executions for this order
                        executions = session.query(Execution).filter_by(order_id=order_id).all()

                        # Capture execution data within the session
                        execution_data = []
                        total_executed_shares = 0
                        for execution in executions:
                            exec_info = {
                                "shares": execution.shares,
                                "price": float(execution.price),
                                "time": execution.executed_at.isoformat() if execution.executed_at else None,
                                "timestamp": int(execution.executed_at.timestamp()) if execution.executed_at else int(time.time())
                            }
                            execution_data.append(exec_info)
                            total_executed_shares += execution.shares

                        # Calculate avg price if needed
                        avg_executed_price = None
                        if total_executed_shares > 0:
                            avg_executed_price = sum(e["shares"] * e["price"] for e in execution_data) / total_executed_shares

                        # Create the status element
                        status_element = ET.Element('status', {'id': trans_id})

                        # Add open status if applicable
                        if order_open_shares != 0 and not order_is_canceled:
                            open_elem = ET.Element('open', {'shares': str(abs(order_open_shares))})
                            status_element.append(open_elem)

                        # Add executions
                        for execution in execution_data:
                            exec_elem = ET.Element('executed', {
                                'shares': str(execution["shares"]),
                                'price': str(execution["price"]),
                                'time': str(execution["timestamp"])
                            })
                            status_element.append(exec_elem)

                        # Add canceled status if applicable
                        if order_is_canceled and order_canceled_at:
                            # Calculate canceled shares
                            canceled_shares = abs(order_amount) - total_executed_shares
                            canceled_shares = max(0, canceled_shares)  # Ensure non-negative

                            cancel_time = int(datetime.datetime.fromisoformat(order_canceled_at).timestamp())
                            canceled_elem = ET.Element('canceled', {
                                'shares': str(canceled_shares),
                                'time': str(cancel_time)
                            })
                            status_element.append(canceled_elem)

                        logger.info(f"Successfully retrieved status for order {order_id}")

                    except Exception as e:
                        logger.exception(f"Error processing order details for {order_id}: {str(e)}")
                        error_element = ET.Element('error', {'id': trans_id, 'error': f"Error processing order details: {str(e)}"})

            # After session is closed, add either the status or error element
            if error_element is not None:
                results_root.append(error_element)
            elif status_element is not None:
                results_root.append(status_element)
            else:
                # This should not happen, but just in case
                results_root.append(ET.Element('error', {'id': trans_id, 'error': "Unknown error occurred"}))

        except ValueError:
            logger.warning(f"Invalid transaction ID format '{trans_id}' in query for account {account_id}")
            results_root.append(ET.Element('error', {'id': trans_id, 'error': "Invalid transaction ID format"}))
        except Exception as e:
            logger.exception(f"Error processing query for order ID '{trans_id}' (Account: {account_id})")
            results_root.append(ET.Element('error', {'id': trans_id, 'error': f'Internal server error during query: {e}'}))
    
    def _process_cancel(self, cancel_elem, account_id, results_root):
        """Process a cancel transaction"""
        attrs = cancel_elem.attrib
        trans_id = attrs.get('id')
        
        if not trans_id:
            logger.warning(f"Cancel tag missing id attribute for account {account_id}")
            results_root.append(ET.Element('error', {'error': "Cancel tag missing id attribute"}))
            return

        # Check permission before calling handle_cancel
        try:
            order_id_int = int(trans_id)
            # Call handle_cancel with the account ID
            logger.info(f"Attempting to cancel order ID: {trans_id} (Account: {account_id})")
            self.handle_cancel(trans_id, results_root, account_id)

        except ValueError:
            logger.warning(f"Invalid transaction ID format '{trans_id}' in cancel for account {account_id}")
            results_root.append(ET.Element('error', {'id': trans_id, 'error': "Invalid transaction ID format"}))
        except Exception as e:
            logger.exception(f"Error checking permission for cancel order ID '{trans_id}' (Account: {account_id})")
            results_root.append(ET.Element('error', {'id': trans_id, 'error': f'Internal server error during cancel pre-check: {e}'}))

    def handle_cancel(self, trans_id, results_root, requesting_account_id):
        """Handle a cancel request and append the result XML element to results_root"""
        try:
            order_id = int(trans_id)

            # Now use the provided requesting_account_id instead of trying to retrieve it.
            if not requesting_account_id:
                # This check might be redundant if handle_transactions validates it, but good for safety
                logger.error("Missing requesting account ID for cancel operation.")
                error_elem = ET.SubElement(results_root, 'error', {'id': trans_id})
                error_elem.text = "Internal error: Missing account context for cancel."
                return

        except ValueError:
            # Log error before returning
            logger.warning(f"Invalid transaction ID format '{trans_id}' in cancel for account {requesting_account_id}")
            error_elem = ET.SubElement(results_root, 'error', {'id': trans_id})
            error_elem.text = "Invalid transaction ID format"
            return

        try:
            # Get current session
            with self.database.session_scope() as session:
                # Pass requesting account ID for permission check inside cancel_order within our session
                order = session.query(Order).filter_by(id=order_id).with_for_update().first()
                if not order:
                    error_elem = ET.SubElement(results_root, 'error', {'id': trans_id})
                    error_elem.text = "Order not found"
                    return

                # === Permission Check ===
                if order.account_id != requesting_account_id:
                    logger.warning(f"Permission denied: Account {requesting_account_id} tried to cancel order {order_id} owned by {order.account_id}")
                    error_elem = ET.SubElement(results_root, 'error', {'id': trans_id})
                    error_elem.text = "Permission denied: Cannot cancel order belonging to another account"
                    return

                # Check if the order has any open shares to cancel (positive for buy, negative for sell)
                if order.open_shares == 0:
                    error_elem = ET.SubElement(results_root, 'error', {'id': trans_id})
                    error_elem.text = "Order already fully executed or canceled"
                    return

                # Prevent canceling already canceled orders
                if order.canceled_at is not None:
                    error_elem = ET.SubElement(results_root, 'error', {'id': trans_id})
                    error_elem.text = "Order already canceled"
                    return

                # Record the cancellation time as datetime
                cancel_time = datetime.datetime.utcnow()

                # Get the account
                account = session.query(Account).filter_by(id=order.account_id).with_for_update().first()
                if not account:
                    # This shouldn't happen if DB constraints are set up
                    error_elem = ET.SubElement(results_root, 'error', {'id': trans_id})
                    error_elem.text = f"Account {order.account_id} not found for order {order_id}"
                    return

                # Store the amount of shares being canceled (always positive)
                canceled_shares_amount = abs(order.open_shares)

                # Refund for buy orders or return shares for sell orders
                if order.amount > 0:  # Buy order
                    # Calculate refund amount based on open shares and limit price
                    refund_amount = canceled_shares_amount * float(order.limit_price)

                    # Update account balance
                    logger.info(f"Refunding {refund_amount} to account {account.id} for canceled buy order {order_id}")
                    account.balance += refund_amount
                else:  # Sell order
                    # Return shares to account position
                    symbol_name = order.symbol_name
                    return_shares = canceled_shares_amount

                    # Get or create position
                    position = session.query(Position).filter_by(
                        account_id=account.id, symbol_name=symbol_name).with_for_update().first()

                    if position:
                        logger.info(f"Returning {return_shares} shares of {symbol_name} to account {account.id} for canceled sell order {order_id}")
                        position.amount += return_shares
                    else:
                        # Create new position if one doesn't exist
                        logger.warning(f"Creating new position with {return_shares} shares of {symbol_name} for account {account.id} from canceled sell order {order_id}")
                        new_position = Position(account_id=account.id, symbol_name=symbol_name, amount=return_shares)
                        session.add(new_position)

                # Update order status
                order.open_shares = 0
                order.canceled_at = cancel_time

                # Success - now fetch executions and create response in the same session
                executions = session.query(Execution).filter_by(order_id=order_id).all()

                canceled_element = ET.SubElement(results_root, 'canceled', {'id': trans_id})

                # Add executions
                total_executed_shares = 0
                for execution in executions:
                    exec_time = int(execution.executed_at.timestamp()) if execution.executed_at else int(time.time())
                    ET.SubElement(canceled_element, 'executed', {
                        'shares': str(execution.shares),
                        'price': str(execution.price),
                        'time': str(exec_time)
                    })
                    total_executed_shares += execution.shares

                # Add canceled part
                canceled_shares = abs(order.amount) - total_executed_shares
                canceled_shares = max(0, canceled_shares)  # Ensure non-negative

                ET.SubElement(canceled_element, 'canceled', {
                    'shares': str(canceled_shares),
                    'time': str(int(cancel_time.timestamp()))
                })

                logger.info(f"Successfully canceled order {order_id} for account {requesting_account_id}")

        except Exception as e:
            logger.exception(f"Error processing cancel request for {trans_id}: {str(e)}")
            error_elem = ET.SubElement(results_root, 'error', {'id': trans_id})
            error_elem.text = f"Internal server error processing cancel request: {str(e)}"

