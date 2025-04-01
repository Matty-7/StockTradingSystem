import socket
import threading
import time
import xml.etree.ElementTree as ET
import random
import sys
from client_test import generate_indent, send_xml_to_server

# Test setup parameters
NUM_THREADS = 10        # Number of concurrent threads
TEST_ACCOUNTS = 5       # Number of test accounts
OPERATIONS_PER_THREAD = 20  # Operations per thread
SYMBOL = "TESTSTOCK"    # Test stock symbol

# Result tracking
success_count = 0
error_count = 0
race_condition_count = 0
success_lock = threading.Lock()

def setup_test_environment(client_socket):
    """Create test environment: accounts and stocks"""
    print("Setting up test environment...")
    
    # Create test accounts and stock
    xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml_str += '<create>\n'
    
    # Create multiple test accounts, each with initial balance of 10000
    for i in range(1, TEST_ACCOUNTS + 1):
        xml_str += generate_indent() + f'<account id="concurrent{i}" balance="10000"/>\n'
    
    # Create stock for account 1
    xml_str += generate_indent() + f'<symbol sym="{SYMBOL}">\n'
    xml_str += generate_indent(2) + f'<account id="concurrent1">10000</account>\n'
    xml_str += generate_indent() + '</symbol>\n'
    
    xml_str += '</create>\n'
    
    response = send_xml_to_server(str(len(xml_str)) + "\n" + xml_str, client_socket)
    print("Test environment setup complete")
    return response

def concurrent_worker(thread_id, client_socket):
    """Work performed by each concurrent thread"""
    global success_count, error_count, race_condition_count
    
    try:
        local_success = 0
        local_error = 0
        local_race = 0
        
        for op in range(OPERATIONS_PER_THREAD):
            # Randomly select operation type: buy, sell, query, cancel
            op_type = random.choice(['buy', 'sell', 'query', 'cancel'])
            
            # Random account ID selection
            account_id = f"concurrent{random.randint(1, TEST_ACCOUNTS)}"
            
            # Execute selected operation
            if op_type == 'buy':
                amount = random.randint(1, 100)
                price = random.uniform(10, 100)
                response = execute_buy(account_id, amount, price, client_socket)
                
            elif op_type == 'sell':
                # Only account 1 has stock to sell
                if account_id == "concurrent1":
                    amount = random.randint(1, 10)
                    price = random.uniform(10, 100)
                    response = execute_sell("concurrent1", amount, price, client_socket)
                else:
                    # Try to sell stock that doesn't exist (edge case test)
                    response = execute_sell(account_id, 1, 50, client_socket)
                
            elif op_type == 'query':
                # Random query of an order ID (may not exist)
                order_id = random.randint(1, 100)
                response = execute_query(account_id, order_id, client_socket)
                
            elif op_type == 'cancel':
                # Random cancel of an order ID (may not exist)
                order_id = random.randint(1, 100)
                response = execute_cancel(account_id, order_id, client_socket)
            
            # Parse response to determine if operation succeeded
            if '<error' in response:
                if 'race' in response.lower() or 'concurrent' in response.lower():
                    local_race += 1
                else:
                    local_error += 1
            else:
                local_success += 1
                
        # Update global counters
        with success_lock:
            success_count += local_success
            error_count += local_error
            race_condition_count += local_race
            
        print(f"Thread {thread_id} completed: success={local_success}, errors={local_error}, race_conditions={local_race}")
            
    except Exception as e:
        print(f"Thread {thread_id} exception: {e}")
        with success_lock:
            error_count += 1

def execute_buy(account_id, amount, price, client_socket):
    """Execute buy operation"""
    xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml_str += f'<transactions id="{account_id}">\n'
    xml_str += generate_indent() + f'<order sym="{SYMBOL}" amount="{amount}" limit="{price:.2f}"/>\n'
    xml_str += '</transactions>\n'
    
    return send_xml_to_server(str(len(xml_str)) + "\n" + xml_str, client_socket)

def execute_sell(account_id, amount, price, client_socket):
    """Execute sell operation"""
    xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml_str += f'<transactions id="{account_id}">\n'
    xml_str += generate_indent() + f'<order sym="{SYMBOL}" amount="-{amount}" limit="{price:.2f}"/>\n'
    xml_str += '</transactions>\n'
    
    return send_xml_to_server(str(len(xml_str)) + "\n" + xml_str, client_socket)

def execute_query(account_id, order_id, client_socket):
    """Execute query operation"""
    xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml_str += f'<transactions id="{account_id}">\n'
    xml_str += generate_indent() + f'<query id="{order_id}"/>\n'
    xml_str += '</transactions>\n'
    
    return send_xml_to_server(str(len(xml_str)) + "\n" + xml_str, client_socket)

def execute_cancel(account_id, order_id, client_socket):
    """Execute cancel operation"""
    xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml_str += f'<transactions id="{account_id}">\n'
    xml_str += generate_indent() + f'<cancel id="{order_id}"/>\n'
    xml_str += '</transactions>\n'
    
    return send_xml_to_server(str(len(xml_str)) + "\n" + xml_str, client_socket)

def test_account_consistency(client_socket):
    """Check account consistency after testing"""
    print("\nChecking account consistency...")
    
    for i in range(1, TEST_ACCOUNTS + 1):
        account_id = f"concurrent{i}"
        # Query account balance and position
        query_account(account_id, client_socket)

def query_account(account_id, client_socket):
    """Helper method to query account information (implementation depends on system)"""
    # Example only - actual implementation depends on your system
    print(f"Checking consistency for account {account_id} (needs implementation based on actual system)")

def run_concurrency_test():
    """Run complete concurrency test"""
    hostname = socket.gethostname()
    server_address = (hostname, 12345)
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    
    try:
        client_socket.connect(server_address)
        print("Connected to server, starting concurrency test...")
        
        # Setup test environment
        setup_test_environment(client_socket)
        
        # Create multiple threads to execute operations simultaneously
        threads = []
        for i in range(NUM_THREADS):
            # Create separate socket connection for each thread
            thread_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            thread_socket.connect(server_address)
            
            t = threading.Thread(target=concurrent_worker, 
                               args=(i, thread_socket))
            threads.append((t, thread_socket))
            t.start()
        
        # Wait for all threads to complete
        for t, s in threads:
            t.join()
            s.close()
            
        # Test account consistency
        test_account_consistency(client_socket)
        
        # Print result statistics
        print("\n=================== CONCURRENCY TEST RESULTS ===================")
        print(f"Total operations: {NUM_THREADS * OPERATIONS_PER_THREAD}")
        print(f"Successful operations: {success_count}")
        print(f"Error operations: {error_count}")
        print(f"Race conditions: {race_condition_count}")
        print("=================================================")
        
    except Exception as e:
        print(f"Concurrency test exception: {e}")
    finally:
        client_socket.close()
        print("Concurrency test completed")

if __name__ == "__main__":
    run_concurrency_test()
