import threading
import time
import socket
import statistics
import matplotlib.pyplot as plt
import numpy as np
import os
import psutil
import shutil
import subprocess
import random
from client_test import send_xml_to_server, generate_indent

def measure_latency(request_count):
    """Measure system latency"""
    latencies = []
    hostname = socket.gethostname()
    server_address = (hostname, 12345)

    for _ in range(request_count):
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            client_socket.connect(server_address)
            request_xml = generate_random_request()
            start_time = time.time()
            send_xml_to_server(request_xml, client_socket)
            end_time = time.time()
            latencies.append(end_time - start_time)
        except Exception as e:
            print(f"Error measuring latency: {e}")
        finally:
            client_socket.close()

    avg_latency = statistics.mean(latencies)
    std_dev_latency = statistics.stdev(latencies) if len(latencies) > 1 else 0
    return avg_latency, std_dev_latency, latencies

def run_performance_test(core_counts, iterations=3):
    """Run performance tests with different core counts"""
    results = {}

    for cores in core_counts:
        set_core_count(cores)

        throughputs, latencies = [], []
        for i in range(iterations):
            print(f"  - Running iteration {i+1}/{iterations} with {cores} cores...")
            throughput = measure_throughput(100)
            avg_latency, std_dev_latency, raw_latencies = measure_latency(100)
            throughputs.append(throughput)
            latencies.append(avg_latency)
            print(f"  - Completed iteration {i+1}: {throughput:.2f} req/sec, Latency: {avg_latency:.6f} sec")

        avg_throughput = statistics.mean(throughputs)
        std_dev_throughput = statistics.stdev(throughputs) if len(throughputs) > 1 else 0
        avg_latency = statistics.mean(latencies)
        std_dev_latency = statistics.stdev(latencies) if len(latencies) > 1 else 0

        results[cores] = {
            "avg_throughput": avg_throughput,
            "std_dev_throughput": std_dev_throughput,
            "avg_latency": avg_latency,
            "std_dev_latency": std_dev_latency,
            "raw_latencies": raw_latencies
        }
        print(f"Completed testing with {cores} cores. Avg throughput: {avg_throughput:.2f} req/sec, Avg latency: {avg_latency:.6f} sec")

    generate_graph(results)
    return results

    return results

def set_core_count(cores):
    """Set the number of cores for the server to use by restarting it"""
    print(f"Setting server to use {cores} cores...")
    
    # Kill existing server if running (find pid by port)
    try:
        import subprocess
        # Find process using port 12345
        result = subprocess.run(["lsof", "-i", ":12345", "-t"], capture_output=True, text=True)
        if result.stdout.strip():
            pid = result.stdout.strip()
            print(f"Killing existing server process (PID: {pid})...")
            subprocess.run(["kill", pid], check=False)
            time.sleep(2)  # Wait for server to terminate
    except Exception as e:
        print(f"Warning: Unable to kill existing server: {e}")
    
    # Start new server process with desired core count
    try:
        server_env = os.environ.copy()
        server_env["CPU_CORES"] = str(cores)
        
        # Get path to server.py (assuming it's in the parent directory)
        server_path = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "server.py"))
        
        # Start server in background
        print(f"Starting server with {cores} cores...")
        subprocess.Popen(["python3", server_path], env=server_env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        # Wait for server to initialize
        time.sleep(3)
        print(f"Server restarted with {cores} cores")
    except Exception as e:
        print(f"Error starting server: {e}")
        raise

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
    """Generate performance graphs for throughput and latency"""
    cores = sorted(results.keys())
    avg_throughputs = [results[c]["avg_throughput"] for c in cores]
    std_devs_throughput = [results[c]["std_dev_throughput"] for c in cores]
    avg_latencies = [results[c]["avg_latency"] for c in cores]
    std_devs_latency = [results[c]["std_dev_latency"] for c in cores]

    plt.figure(figsize=(10, 6))
    plt.errorbar(cores, avg_throughputs, yerr=std_devs_throughput, fmt='o-', capsize=5, label='Throughput')
    plt.xlabel("Number of Cores")
    plt.ylabel("Throughput (requests/second)")
    plt.title("Throughput vs Number of Cores")
    plt.grid(True)
    plt.legend()
    plt.savefig("writeup/throughput_vs_cores.png")
    plt.close()

    plt.figure(figsize=(10, 6))
    plt.errorbar(cores, avg_latencies, yerr=std_devs_latency, fmt='o-', capsize=5, label='Latency', color='r')
    plt.xlabel("Number of Cores")
    plt.ylabel("Latency (seconds)")
    plt.title("Latency vs Number of Cores")
    plt.grid(True)
    plt.legend()
    plt.savefig("writeup/latency_vs_cores.png")
    plt.close()


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
            print(f"  {cores} cores: {data['avg_throughput']:.2f} req/sec (±{data['std_dev_throughput']:.2f})")
            print(f"  {cores} cores: {data['avg_latency']:.2f} sec (±{data['std_dev_latency']:.2f})")
    except Exception as e:
        print(f"Performance test failed with error: {e}")
