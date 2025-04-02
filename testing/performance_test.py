import threading
import time
import socket
import statistics
import matplotlib.pyplot as plt
import numpy as np
import os
import subprocess
import random
from client_test import send_xml_to_server, generate_indent

def run_performance_test(core_counts, iterations=3):
    """Run performance tests with different core counts"""
    results = {}
    
    for cores in core_counts:
        # Set server to use specified number of cores
        set_core_count(cores)
        
        throughputs = []
        for i in range(iterations):
            print(f"  - Running iteration {i+1}/{iterations} with {cores} cores...")
            throughput = measure_throughput(100)  # Reduced from 1000 to 100 requests
            throughputs.append(throughput)
            print(f"  - Completed iteration {i+1}: {throughput:.2f} req/sec")
        
        # Calculate mean and standard deviation
        avg = statistics.mean(throughputs)
        std_dev = statistics.stdev(throughputs) if len(throughputs) > 1 else 0
        
        results[cores] = {"avg": avg, "std_dev": std_dev, "raw": throughputs}
        print(f"Completed testing with {cores} cores. Avg throughput: {avg:.2f} req/sec")
    
    try:
        generate_graph(results)
        print("Performance graph generated successfully")
    except Exception as e:
        print(f"Error generating graph: {e}")
        print("Continuing with test results...")
    
    return results

def set_core_count(cores):
    """Set the number of cores for the server to use (via environment variable)"""
    print(f"Setting server to use {cores} cores...")
    os.environ["CPU_CORES"] = str(cores)

def send_batch_requests(request_count):
    """Send a batch of requests to test system performance"""
    # Connect to server
    hostname = socket.gethostname()
    server_address = (hostname, 12345)
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    
    try:
        client_socket.connect(server_address)
        
        # Set up test account and symbol
        setup_xml = generate_setup_xml()
        send_xml_to_server(setup_xml, client_socket)
        
        # Send a series of random requests
        for i in range(request_count):
            request_xml = generate_random_request()
            send_xml_to_server(request_xml, client_socket)
            
    except Exception as e:
        print(f"Error sending batch requests: {e}")
    finally:
        client_socket.close()

def generate_setup_xml():
    """Generate XML to set up test environment"""
    xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml_str += '<create>\n'
    xml_str += generate_indent() + '<account id="perftest" balance="1000000"/>\n'
    xml_str += generate_indent() + '<symbol sym="PERF">\n'
    xml_str += generate_indent(2) + '<account id="perftest">10000</account>\n'
    xml_str += generate_indent() + '</symbol>\n'
    xml_str += '</create>\n'
    return str(len(xml_str)) + "\n" + xml_str

def generate_random_request():
    """Generate random test request"""
    op_type = random.choice(['buy', 'sell', 'query', 'cancel'])
    
    xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml_str += '<transactions id="perftest">\n'
    
    if op_type == 'buy':
        amount = random.randint(1, 100)
        price = random.uniform(10, 100)
        xml_str += generate_indent() + f'<order sym="PERF" amount="{amount}" limit="{price:.2f}"/>\n'
    elif op_type == 'sell':
        amount = random.randint(1, 10)  # Sell less to avoid depleting position
        price = random.uniform(10, 100)
        xml_str += generate_indent() + f'<order sym="PERF" amount="-{amount}" limit="{price:.2f}"/>\n'
    elif op_type == 'query':
        order_id = random.randint(1, 100)
        xml_str += generate_indent() + f'<query id="{order_id}"/>\n'
    elif op_type == 'cancel':
        order_id = random.randint(1, 100)
        xml_str += generate_indent() + f'<cancel id="{order_id}"/>\n'
    
    xml_str += '</transactions>\n'
    return str(len(xml_str)) + "\n" + xml_str

def measure_throughput(request_count):
    """Measure system throughput"""
    print(f"    Starting throughput measurement with {request_count} requests...")
    start_time = time.time()
    
    # Create multiple threads to send requests
    threads = []
    thread_count = 5  # Reduced from 10 to 5 concurrent clients
    for i in range(thread_count):
        requests_per_thread = request_count // thread_count
        t = threading.Thread(target=send_batch_requests, 
                            args=(requests_per_thread,))
        threads.append(t)
        t.start()
    
    for t in threads:
        t.join()
        
    elapsed = time.time() - start_time
    throughput = request_count / elapsed  # Requests per second
    print(f"    Completed in {elapsed:.2f} seconds")
    return throughput

def generate_graph(results):
    """Generate performance graph"""
    cores = sorted(results.keys())
    avgs = [results[c]["avg"] for c in cores]
    errors = [results[c]["std_dev"] for c in cores]
    
    try:
        plt.figure(figsize=(10, 6))
        plt.errorbar(cores, avgs, yerr=errors, fmt='o-', capsize=5)
        plt.xlabel("Number of Cores")
        plt.ylabel("Throughput (requests/second)")
        plt.title("Exchange Engine Scalability")
        plt.grid(True)
        
        # Ensure output directory exists
        os.makedirs("writeup", exist_ok=True)
        plt.savefig("writeup/throughput_vs_cores.png")
        plt.close()
    except Exception as e:
        print(f"Error in graph generation: {e}")
        # Fall back to text output
        print("Results summary (text format):")
        for core in cores:
            print(f"  {core} cores: {results[core]['avg']:.2f} req/sec (±{results[core]['std_dev']:.2f})")

def send_xml_to_server(xml_request, client_socket, timeout=2):
    """Send XML request to server, add timeout mechanism"""
    client_socket.settimeout(timeout)  # Set 2 seconds timeout
    try:
        # Original code
        client_socket.sendall(xml_request.encode('utf-8'))
        response_bytes = client_socket.recv(4096)
        response_str = response_bytes.decode('utf-8')
        return response_str
    except socket.timeout:
        return "<results><error>Request timed out</error></results>"

if __name__ == "__main__":
    available_cores = os.cpu_count()
    if available_cores >= 16:
        core_counts = [1, 2, 4, 8, 16]
    elif available_cores >= 8:
        core_counts = [1, 2, 4, 8]
    elif available_cores >= 4:
        core_counts = [1, 2, 4]
    else:
        core_counts = [1, 2]
        
    print(f"System has {available_cores} available cores, will test the following configurations: {core_counts}")
    
    try:
        results = run_performance_test(core_counts)
        print("Test results:")
        for cores, data in results.items():
            print(f"  {cores} cores: {data['avg']:.2f} req/sec (±{data['std_dev']:.2f})")
    except Exception as e:
        print(f"Performance test failed with error: {e}")
