import xml.etree.ElementTree as ET
import time
import datetime
import logging

# Setup logger for this module
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO) # Or DEBUG for more verbosity
# Add handler if not configured globally (e.g., in server.py)
# handler = logging.StreamHandler()
# formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
# handler.setFormatter(formatter)
# logger.addHandler(handler)

class XMLHandler:
    def __init__(self, database, matching_engine):
        self.database = database
        self.matching_engine = matching_engine
        # Use the module-level logger
        # self.logger = logging.getLogger("XMLHandler")

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

        for child in root:
            if child.tag == 'account':
                account_id = child.attrib.get('id')
                balance = child.attrib.get('balance')

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
                    continue

                try:
                    amount_val = float(amount_str)
                    limit_val = float(limit_str)
                except ValueError:
                    error_text = "Invalid numeric value for amount or limit"
                    logger.warning(f"{error_text} (amount='{amount_str}', limit='{limit_str}') for account {account_id}")
                    err_attrs = attrs.copy()
                    err_attrs['error'] = error_text
                    results_root.append(ET.Element('error', err_attrs))
                    continue

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

            elif elem_name == 'query':
                trans_id = attrs.get('id')
                if not trans_id:
                    logger.warning(f"Query tag missing id attribute for account {account_id}")
                    results_root.append(ET.Element('error', {'error': "Query tag missing id attribute"}))
                    continue
                try:
                    order_id = int(trans_id)
                    logger.info(f"Querying status for order ID: {order_id} (Account: {account_id})")
                    order = self.database.get_order(order_id)

                    if order:
                        # Check if the order belongs to the requesting account
                        if order.account_id != account_id:
                            logger.warning(f"Account {account_id} attempted to query order {order_id} belonging to account {order.account_id}")
                            results_root.append(ET.Element('error', {'id': trans_id, 'error': "Permission denied: Order belongs to another account"}))
                            continue

                        status_parts, error_msg = self.database.get_status(order)
                        if error_msg:
                            logger.error(f"Error getting status for order {order_id}: {error_msg}")
                            results_root.append(ET.Element('error', {'id': trans_id, 'error': error_msg}))
                        else:
                            status_element = ET.Element('status', {'id': trans_id})
                            logger.debug(f"Order {order_id} status parts: {status_parts}")
                            for part_xml in status_parts:
                                try:
                                    part_element = ET.fromstring(part_xml)
                                    status_element.append(part_element)
                                except ET.ParseError as pe:
                                    logger.error(f"Failed to parse status part XML for order {order_id}: {part_xml}, Error: {pe}")
                                    error_part = ET.Element('error')
                                    error_part.text = f"Internal error: Invalid status format from DB"
                                    status_element.append(error_part)
                            results_root.append(status_element)
                            logger.info(f"Successfully retrieved status for order {order_id}")
                    else:
                        logger.warning(f"Query failed: Order ID {order_id} not found (Account: {account_id})")
                        results_root.append(ET.Element('error', {'id': trans_id, 'error': "Order not found"}))
                except ValueError:
                    logger.warning(f"Invalid transaction ID format '{trans_id}' in query for account {account_id}")
                    results_root.append(ET.Element('error', {'id': trans_id, 'error': "Invalid transaction ID format"}))
                except Exception as e:
                    logger.exception(f"Error processing query for order ID '{trans_id}' (Account: {account_id})")
                    results_root.append(ET.Element('error', {'id': trans_id, 'error': f'Internal server error during query: {e}'}))

            elif elem_name == 'cancel':
                trans_id = attrs.get('id')
                if not trans_id:
                    logger.warning(f"Cancel tag missing id attribute for account {account_id}")
                    results_root.append(ET.Element('error', {'error': "Cancel tag missing id attribute"}))
                    continue

                # Check permission before calling handle_cancel
                try:
                    order_id_int = int(trans_id)
                    order_to_cancel = self.database.get_order(order_id_int)
                    if not order_to_cancel:
                         logger.warning(f"Cancel failed: Order ID {trans_id} not found (Account: {account_id})")
                         results_root.append(ET.Element('error', {'id': trans_id, 'error': "Order not found"}))
                         continue
                    if order_to_cancel.account_id != account_id:
                        logger.warning(f"Account {account_id} attempted to cancel order {trans_id} belonging to account {order_to_cancel.account_id}")
                        results_root.append(ET.Element('error', {'id': trans_id, 'error': "Permission denied: Order belongs to another account"}))
                        continue

                    # Permission granted, proceed with cancellation
                    logger.info(f"Attempting to cancel order ID: {trans_id} (Account: {account_id})")
                    self.handle_cancel(trans_id, results_root)

                except ValueError:
                    logger.warning(f"Invalid transaction ID format '{trans_id}' in cancel for account {account_id}")
                    results_root.append(ET.Element('error', {'id': trans_id, 'error': "Invalid transaction ID format"}))
                except Exception as e:
                     logger.exception(f"Error checking permission for cancel order ID '{trans_id}' (Account: {account_id})")
                     results_root.append(ET.Element('error', {'id': trans_id, 'error': f'Internal server error during cancel pre-check: {e}'}))

            else:
                 logger.warning(f"Unknown transaction type '{elem_name}' in request for account {account_id}")
                 results_root.append(ET.Element('error', {'type': elem_name, 'error': f"Unknown transaction type: {elem_name}"}))

        response_str = ET.tostring(results_root, encoding='utf-8').decode('utf-8')
        logger.debug(f"Sending response for account {account_id}: {response_str[:500]}...")
        return response_str

    def handle_cancel(self, trans_id, results_root):
        """Handle a cancel request and append the result XML element to results_root"""
        try:
            order_id = int(trans_id)
        except ValueError:
            error_elem = ET.SubElement(results_root, 'error', {'id': trans_id})
            error_elem.text = "Invalid transaction ID format"
            return

        try:
            success, error_msg = self.database.cancel_order(order_id)

            if success:
                # Get the updated order status to build the response
                order = self.database.get_order(order_id)
                if not order:
                    # Should not happen if cancel succeeded, but handle defensively
                    error_elem = ET.SubElement(results_root, 'error', {'id': trans_id})
                    error_elem.text = "Failed to retrieve order status after cancellation"
                    return

                canceled_element = ET.SubElement(results_root, 'canceled', {'id': trans_id})

                # Fetch executions separately as get_status doesn't return raw execution objects
                executions = self.database.get_order_executions(order_id)
                total_executed_shares = 0
                for execution in executions:
                    exec_time_int = int(execution.executed_at.timestamp()) if execution.executed_at else int(time.time())
                    ET.SubElement(canceled_element, 'executed', {
                        'shares': str(execution.shares),
                        'price': str(execution.price),
                        'time': str(exec_time_int)
                    })
                    total_executed_shares += execution.shares

                # Add the canceled part
                if order.canceled_at:
                    canceled_shares_amount = abs(order.amount) - total_executed_shares
                    # Ensure non-negative
                    canceled_shares_amount = max(0, canceled_shares_amount)
                    canceled_time_int = int(order.canceled_at.timestamp())
                    ET.SubElement(canceled_element, 'canceled', {
                        'shares': str(canceled_shares_amount),
                        'time': str(canceled_time_int)
                    })
                else:
                     # This case indicates a potential issue if cancel succeeded but canceled_at is not set
                     self.logger.error(f"Order {order_id} cancel succeeded but canceled_at is None.")
                     error_elem = ET.SubElement(results_root, 'error', {'id': trans_id})
                     error_elem.text = "Internal error: Order cancel status inconsistent"

            else:
                # Error response from cancel_order
                error_elem = ET.SubElement(results_root, 'error', {'id': trans_id})
                error_elem.text = error_msg

        except Exception as e:
            self.logger.exception(f"Error processing cancel request for {trans_id}: {str(e)}")
            error_elem = ET.SubElement(results_root, 'error', {'id': trans_id})
            error_elem.text = f"Internal server error processing cancel request: {str(e)}"

