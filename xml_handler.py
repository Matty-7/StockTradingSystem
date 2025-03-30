import xml.etree.ElementTree as ET
import time
import datetime

class XMLHandler:
    def __init__(self, database, matching_engine):
        self.database = database
        self.matching_engine = matching_engine
    
    def process_request(self, xml_data):
        """处理XML请求并返回XML响应"""
        try:
            root = ET.fromstring(xml_data)
            
            if root.tag == 'create':
                return self.handle_create(root)
            elif root.tag == 'transactions':
                return self.handle_transactions(root)
            else:
                return f'<results><error>Unknown request type: {root.tag}</error></results>'
        except ET.ParseError:
            return '<results><error>Invalid XML</error></results>'
        except Exception as e:
            return f'<results><error>Error processing request: {str(e)}</error></results>'
    
    def handle_create(self, root):
        """Handle create requests"""
        results = []
        
        for child in root:
            if child.tag == 'account':
                account_id = child.attrib.get('id')
                balance = child.attrib.get('balance')
                
                success, error = self.database.create_account(account_id, float(balance))
                if success:
                    results.append(f'<created id="{account_id}"/>')
                else:
                    results.append(f'<error id="{account_id}">{error}</error>')
            
            elif child.tag == 'symbol':
                symbol = child.attrib.get('sym')
                
                for account_elem in child:
                    if account_elem.tag == 'account':
                        account_id = account_elem.attrib.get('id')
                        amount = float(account_elem.text)
                        
                        success, error = self.database.create_symbol(symbol, account_id, amount)
                        if success:
                            results.append(f'<created sym="{symbol}" id="{account_id}"/>')
                        else:
                            results.append(f'<error sym="{symbol}" id="{account_id}">{error}</error>')
        
        return '<results>' + ''.join(results) + '</results>'
    
    def handle_transactions(self, root):
        """Handle transaction requests"""
        account_id = root.attrib.get('id')
        results = []
        
        # Check if account exists
        account = self.database.get_account(account_id)
        if not account:
            # Return error for each child
            for child in root:
                if child.tag == 'order':
                    sym = child.attrib.get('sym')
                    amount = child.attrib.get('amount')
                    limit = child.attrib.get('limit')
                    results.append(f'<error sym="{sym}" amount="{amount}" limit="{limit}">Account not found</error>')
                elif child.tag == 'query' or child.tag == 'cancel':
                    trans_id = child.attrib.get('id')
                    results.append(f'<error id="{trans_id}">Account not found</error>')
            return '<results>' + ''.join(results) + '</results>'
        
        for child in root:
            if child.tag == 'order':
                sym = child.attrib.get('sym')
                amount = float(child.attrib.get('amount'))
                limit = child.attrib.get('limit')
                
                success, error, order = self.matching_engine.place_order(account_id, sym, amount, limit)
                if success:
                    results.append(f'<opened sym="{sym}" amount="{amount}" limit="{limit}" id="{order.id}"/>')
                else:
                    results.append(f'<error sym="{sym}" amount="{amount}" limit="{limit}">{error}</error>')
            
            elif child.tag == 'query':
                trans_id = child.attrib.get('id')
                order = self.database.get_order(int(trans_id))
                
                if order:
                    status_parts = order.get_status()
                    results.append(f'<status id="{trans_id}">' + ''.join(status_parts) + '</status>')
                else:
                    results.append(f'<error id="{trans_id}">Order not found</error>')
            
            elif child.tag == 'cancel':
                trans_id = child.attrib.get('id')
                success, error = self.database.cancel_order(int(trans_id))
                
                if success:
                    order = self.database.get_order(int(trans_id))
                    status_parts = order.get_status()
                    results.append(f'<canceled id="{trans_id}">' + ''.join(status_parts) + '</canceled>')
                else:
                    results.append(f'<error id="{trans_id}">{error}</error>')
        
        return '<results>' + ''.join(results) + '</results>' 
