import socket
import threading
import time
import xml.etree.ElementTree as ET
import random
import sys
from client_test import generate_indent, send_xml_to_server

# Test setup parameters
NUM_THREADS = 20        # Number of concurrent threads
TEST_ACCOUNTS = 5       # Number of test accounts
OPERATIONS_PER_THREAD = 300  # Operations per thread
SYMBOL = "TESTSTOCK"    # Test stock symbol

# Result tracking
success_count = 0
error_count = 0
race_condition_count = 0
success_lock = threading.Lock()

# Global order tracking
order_tracking = {}     # {account_id: [order_ids]}
order_tracking_lock = threading.Lock()

def setup_test_environment(client_socket):
    """Create test environment: accounts and stocks"""
    print("Setting up test environment...")

    # Create test accounts and stock
    xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml_str += '<create>\n'

    # add more accounts with high balances
    for i in range(1, TEST_ACCOUNTS + 1):
        xml_str += generate_indent() + f'<account id="concurrent{i}" balance="500000"/>\n'

    # assign stocks to ALL accounts
    xml_str += generate_indent() + f'<symbol sym="{SYMBOL}">\n'
    # Each account gets different share amounts to test various scenarios
    xml_str += generate_indent(2) + f'<account id="concurrent1">100000</account>\n'
    xml_str += generate_indent(2) + f'<account id="concurrent2">80000</account>\n'
    xml_str += generate_indent(2) + f'<account id="concurrent3">60000</account>\n'
    xml_str += generate_indent(2) + f'<account id="concurrent4">40000</account>\n'
    xml_str += generate_indent(2) + f'<account id="concurrent5">20000</account>\n'
    xml_str += generate_indent() + '</symbol>\n'

    xml_str += '</create>\n'

    response = send_xml_to_server(str(len(xml_str)) + "\n" + xml_str, client_socket)
    print("Test environment setup complete")
    return response

def parse_order_id(response):
    """parse order ID from response"""
    try:
        # parse XML response
        if '<opened' in response:
            # use XML parsing to extract ID
            root = ET.fromstring(response)
            for opened in root.findall('.//opened'):
                if 'id' in opened.attrib:
                    return opened.get('id')
    except Exception as e:
        print(f"Error parsing order ID: {e}")
    return None

def concurrent_worker(thread_id, client_socket):
    """Work performed by each concurrent thread"""
    global success_count, error_count, race_condition_count, order_tracking

    try:
        local_success = 0
        local_error = 0
        local_race = 0

        # record successful orders for each account
        local_orders = {}

        # Start with a few guaranteed successful operations
        if thread_id % TEST_ACCOUNTS < 3:  # First 3 threads perform safer operations
            # First create some guaranteed successful orders
            account_id = f"concurrent{(thread_id % TEST_ACCOUNTS) + 1}"
            # Small buy order
            small_amount = random.randint(1, 5)
            small_price = random.uniform(10, 30)
            response = execute_buy(account_id, small_amount, small_price, client_socket)

            # Track success/failure
            if '<error' in response:
                local_error += 1
            else:
                local_success += 1
                # If successful, record order ID
                order_id = parse_order_id(response)
                if order_id:
                    with order_tracking_lock:
                        if account_id not in order_tracking:
                            order_tracking[account_id] = []
                        order_tracking[account_id].append(order_id)

                        if account_id not in local_orders:
                            local_orders[account_id] = []
                        local_orders[account_id].append(order_id)

        for op in range(OPERATIONS_PER_THREAD - 1 if thread_id % TEST_ACCOUNTS < 3 else OPERATIONS_PER_THREAD):  # Adjust for initial guaranteed operation

            op_weights = {
                'buy': 0.5,     # higher probability to buy, create orders
                'sell': 0.2,    # moderate probability to sell
                'query': 0.2,   # moderate probability to query
                'cancel': 0.1   # lower probability to cancel
            }

            # if there are existing orders, increase the weight of query and cancel
            with order_tracking_lock:
                if any(len(orders) > 0 for orders in order_tracking.values()):
                    op_weights['buy'] = 0.3
                    op_weights['sell'] = 0.2
                    op_weights['query'] = 0.4
                    op_weights['cancel'] = 0.1

            # select operation type based on weights
            op_types = list(op_weights.keys())
            op_type = random.choices(op_types, weights=list(op_weights.values()))[0]

            # random account ID selection
            if op_type == 'sell':
                # only select from accounts with stocks (now all accounts have stocks)
                account_id = f"concurrent{random.randint(1, TEST_ACCOUNTS)}"
            else:
                account_id = f"concurrent{random.randint(1, TEST_ACCOUNTS)}"

            # execute selected operation
            if op_type == 'buy':
                # appropriate amount range to make transactions more likely to succeed
                amount = random.randint(1, 10)  # Even smaller purchase amount
                price = random.uniform(10, 50)  # Lower price range
                response = execute_buy(account_id, amount, price, client_socket)

                # if successful, record order ID
                order_id = parse_order_id(response)
                if order_id:
                    with order_tracking_lock:
                        if account_id not in order_tracking:
                            order_tracking[account_id] = []
                        order_tracking[account_id].append(order_id)

                        if account_id not in local_orders:
                            local_orders[account_id] = []
                        local_orders[account_id].append(order_id)

            elif op_type == 'sell':
                # All accounts now have stock
                amount = random.randint(1, 3)  # Even smaller sell amount to avoid stock shortage
                price = random.uniform(10, 50)  # Lower price range
                response = execute_sell(account_id, amount, price, client_socket)

                # if successful, record order ID
                order_id = parse_order_id(response)
                if order_id:
                    with order_tracking_lock:
                        if account_id not in order_tracking:
                            order_tracking[account_id] = []
                        order_tracking[account_id].append(order_id)

                        if account_id not in local_orders:
                            local_orders[account_id] = []
                        local_orders[account_id].append(order_id)

            elif op_type == 'query':
                # select known order ID for query
                order_id = None
                with order_tracking_lock:
                    if account_id in order_tracking and order_tracking[account_id]:
                        # 95% probability to use known ID, 5% probability to use random ID
                        if random.random() < 0.95:
                            order_id = random.choice(order_tracking[account_id])

                # if there is no known ID, use random ID (still keep some error tests)
                if not order_id:
                    # Use a much smaller range for random IDs to increase chances of hitting real IDs
                    order_id = random.randint(1, 100)

                response = execute_query(account_id, order_id, client_socket)

            elif op_type == 'cancel':
                # select known order ID for cancel
                order_id = None
                with order_tracking_lock:
                    # first select orders created by local thread
                    if account_id in local_orders and local_orders[account_id]:
                        if random.random() < 0.9:  # 90% chance to use known ID
                            order_id = random.choice(local_orders[account_id])
                    # then select global orders
                    elif account_id in order_tracking and order_tracking[account_id]:
                        if random.random() < 0.7:  # 70% chance to use global known ID
                            order_id = random.choice(order_tracking[account_id])

                # if there is no known ID, use random ID with smaller range
                if not order_id:
                    order_id = random.randint(1, 100)

                response = execute_cancel(account_id, order_id, client_socket)

                # if cancel successful, remove from tracking list
                if '<canceled' in response and order_id:
                    with order_tracking_lock:
                        if account_id in order_tracking and order_id in order_tracking[account_id]:
                            order_tracking[account_id].remove(order_id)
                        if account_id in local_orders and order_id in local_orders[account_id]:
                            local_orders[account_id].remove(order_id)

            # parse response to determine if operation is successful
            if '<error' in response:
                if 'race' in response.lower() or 'concurrent' in response.lower():
                    local_race += 1
                else:
                    local_error += 1
            else:
                local_success += 1

        # update global counters
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

def run_concurrency_test():
    """Run complete concurrency test"""
    hostname = socket.gethostname()
    server_address = (hostname, 12345)
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    try:
        client_socket.connect(server_address)
        print("Connected to server, starting concurrency test...")

        # reset global variables
        global success_count, error_count, race_condition_count, order_tracking
        success_count = 0
        error_count = 0
        race_condition_count = 0
        order_tracking = {}

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

        # calculate success rate
        total_ops = NUM_THREADS * OPERATIONS_PER_THREAD
        success_rate = (success_count / total_ops) * 100 if total_ops > 0 else 0

        print("\n=================== CONCURRENCY TEST RESULTS ===================")
        print(f"Total operations: {total_ops}")
        print(f"Successful operations: {success_count} ({success_rate:.2f}%)")
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
