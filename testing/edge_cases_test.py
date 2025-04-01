import socket
from client_test import send_xml_to_server

def test_zero_balance_account():
    """Test account with zero balance"""
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml += '<create>\n'
    xml += '  <account id="zero_bal" balance="0"/>\n'
    xml += '</create>\n'
    return str(len(xml)) + "\n" + xml

def test_max_order_size():
    """Test extremely large order size"""
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml += '<transactions id="123456">\n'
    xml += '  <order sym="SPY" amount="1000000" limit="100"/>\n'
    xml += '</transactions>\n'
    return str(len(xml)) + "\n" + xml

def test_race_condition():
    """Test for potential race conditions"""
    # Prepare multiple transactions with same amount to try to trigger race conditions
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml += '<transactions id="123456">\n'
    for i in range(10):
        xml += f'  <order sym="SPY" amount="10" limit="100"/>\n'
    xml += '</transactions>\n'
    return str(len(xml)) + "\n" + xml

def run_edge_case_tests():
    """Run all edge case tests"""
    hostname = socket.gethostname()
    server_address = (hostname, 12345)
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    
    try:
        client_socket.connect(server_address)
        print("Starting edge case tests...")
        
        # Run various edge case tests
        send_xml_to_server(test_zero_balance_account(), client_socket)
        send_xml_to_server(test_max_order_size(), client_socket)
        send_xml_to_server(test_race_condition(), client_socket)
        
        print("Edge case tests completed")
    finally:
        client_socket.close()

if __name__ == "__main__":
    run_edge_case_tests()
