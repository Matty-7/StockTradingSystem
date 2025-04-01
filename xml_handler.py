import xml.etree.ElementTree as ET
import time
import datetime
import logging

class XMLHandler:
    def __init__(self, database, matching_engine):
        self.database = database
        self.matching_engine = matching_engine
        self.logger = logging.getLogger("XMLHandler")

    def process_request(self, xml_data):
        """Process XML request and return XML response"""
        try:
            root = ET.fromstring(xml_data)

            if root.tag == 'create':
                self.logger.info("Processing create request")
                return self.handle_create(root)
            elif root.tag == 'transactions':
                self.logger.info("Processing transactions request")
                return self.handle_transactions(root)
            else:
                self.logger.warning(f"Unknown request type: {root.tag}")
                return f'<results><error>Unknown request type: {root.tag}</error></results>'
        except ET.ParseError as e:
            self.logger.error(f"XML parse error: {e}")
            return '<results><error>Invalid XML</error></results>'
        except Exception as e:
            self.logger.exception("Unexpected error processing request")
            return f'<results><error>Error processing request: {str(e)}</error></results>'

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
            return '<results><error>Missing account ID</error></results>'

        results_root = ET.Element('results')

        # Validate account existence
        account = self.database.get_account(account_id)
        if not account:
            # Return error for each child
            for child in root:
                if child.tag == 'order':
                    sym = child.attrib.get('sym')
                    amount = child.attrib.get('amount')
                    limit = child.attrib.get('limit')
                    results_root.append(ET.Element('error', {'sym': sym, 'amount': amount, 'limit': limit}))
                elif child.tag == 'query' or child.tag == 'cancel':
                    trans_id = child.attrib.get('id')
                    results_root.append(ET.Element('error', {'id': trans_id}))
            return ET.tostring(results_root, encoding='utf-8').decode('utf-8')

        for child in root:
            if child.tag == 'order':
                sym = child.attrib.get('sym')
                if not sym:
                    error_elem = ET.SubElement(results_root, 'error')
                    error_elem.text = "Missing symbol attribute"
                    continue

                try:
                    amount_val = float(child.attrib.get('amount', '0'))
                    limit_val = float(child.attrib.get('limit', '0'))
                except ValueError:
                    error_elem = ET.SubElement(results_root, 'error')
                    error_elem.set('sym', sym)
                    error_elem.text = "Invalid amount or limit value"
                    continue

                # Use original string attributes for response if possible, otherwise format floats
                amount_str = child.attrib.get('amount', '0')
                limit_str = child.attrib.get('limit', '0')

                success, error_msg, order_id = self.matching_engine.place_order(account_id, sym, amount_val, limit_val)
                if success:
                    # Convert all attribute values to strings
                    results_root.append(ET.Element('opened', {
                        'sym': sym,
                        'amount': amount_str,
                        'limit': limit_str,
                        'id': str(order_id) # Convert order ID to string
                    }))
                else:
                    # Convert all attribute values to strings
                    results_root.append(ET.Element('error', {
                        'sym': sym,
                        'amount': amount_str,
                        'limit': limit_str,
                        'error': str(error_msg) # Ensure error message is a string
                    }))

            elif child.tag == 'query':
                trans_id = child.attrib.get('id')
                if not trans_id:
                    results_root.append(ET.Element('error', {'error': "Query tag missing id attribute"}))
                    continue
                try:
                    order_id = int(trans_id)
                    order = self.database.get_order(order_id)

                    if order:
                        status_parts, error_msg = self.database.get_status(order)
                        if error_msg:
                            results_root.append(ET.Element('error', {'id': trans_id, 'error': error_msg}))
                        else:
                            status_element = ET.Element('status', {'id': trans_id})
                            for part_xml in status_parts:
                                try:
                                    # Attempt to parse each part as XML and append
                                    part_element = ET.fromstring(part_xml)
                                    status_element.append(part_element)
                                except ET.ParseError:
                                    self.logger.error(f"Failed to parse status part XML: {part_xml}")
                                    # Append an error or skip, depending on desired behavior
                                    error_part = ET.Element('error')
                                    error_part.text = f"Invalid status part format: {part_xml}"
                                    status_element.append(error_part)
                            results_root.append(status_element)
                    else:
                        results_root.append(ET.Element('error', {'id': trans_id, 'error': "Order not found"}))
                except ValueError:
                     results_root.append(ET.Element('error', {'id': trans_id, 'error': "Invalid transaction ID format"}))
                except Exception as e:
                    self.logger.exception(f"Error processing query for {trans_id}: {e}")
                    results_root.append(ET.Element('error', {'id': trans_id, 'error': f'Internal server error during query: {e}'}))

            elif child.tag == 'cancel':
                trans_id = child.attrib.get('id')
                if not trans_id:
                    results_root.append(ET.Element('error', {'error': "Cancel tag missing id attribute"}))
                    continue
                self.handle_cancel(trans_id, results_root)

        return ET.tostring(results_root, encoding='utf-8').decode('utf-8')


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

