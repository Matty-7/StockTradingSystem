import xml.etree.ElementTree as ET
import time
import datetime
import logging
import io

class XMLHandler:
    def __init__(self, database, matching_engine):
        self.database = database
        self.matching_engine = matching_engine
        self.logger = logging.getLogger("XMLHandler")
        self.cache = {}
    
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
                            results_root.append(ET.Element('created', {'sym': symbol, 'id': account_id}))
                        else:
                            results_root.append(ET.Element('error', {'sym': symbol, 'id': account_id, 'error': error}))
        
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
                    amount = float(child.attrib.get('amount', '0'))
                    limit = float(child.attrib.get('limit', '0'))
                except ValueError:
                    error_elem = ET.SubElement(results_root, 'error')
                    error_elem.set('sym', sym)
                    error_elem.text = "Invalid amount or limit value"
                    continue
                
                success, error, order = self.matching_engine.place_order(account_id, sym, amount, limit)
                if success:
                    results_root.append(ET.Element('opened', {'sym': sym, 'amount': amount, 'limit': limit, 'id': order.id}))
                else:
                    results_root.append(ET.Element('error', {'sym': sym, 'amount': amount, 'limit': limit, 'error': error}))
            
            elif child.tag == 'query':
                trans_id = child.attrib.get('id')
                order = self.database.get_order(int(trans_id))
                
                if order:
                    status_parts = order.get_status()
                    results_root.append(ET.Element('status', {'id': trans_id}, status_parts))
                else:
                    results_root.append(ET.Element('error', {'id': trans_id}))
            
            elif child.tag == 'cancel':
                trans_id = child.attrib.get('id')
                success, error = self.database.cancel_order(int(trans_id))
                
                if success:
                    order = self.database.get_order(int(trans_id))
                    status_parts = order.get_status()
                    results_root.append(ET.Element('canceled', {'id': trans_id}, status_parts))
                else:
                    results_root.append(ET.Element('error', {'id': trans_id, 'error': error}))
        
        return ET.tostring(results_root, encoding='utf-8').decode('utf-8')
    
    def process_large_request(self, xml_data):
        """Process large XML requests using incremental parsing"""
        context = ET.iterparse(io.StringIO(xml_data), events=("start", "end"))
        results = []
        
        # Process the XML incrementally
        for event, elem in context:
            if event == "end" and elem.tag == "account":
                # Process account element
                # ...
                elem.clear()  # Free memory
                
        return '<results>' + ''.join(results) + '</results>' 
