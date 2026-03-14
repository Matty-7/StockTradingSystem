import threading
import time
import socket
import statistics
import matplotlib.pyplot as plt
import os
import subprocess
import random
import sys
from client_test import generate_indent

MATCH_LATENCY_FILE = '/tmp/match_latencies.csv'

_ACCOUNT_COUNT = 50
_ACCOUNT_PREFIX = "mperf"
_SYMBOL = "MPERF"


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

def _setup_xml():
    """Create 50 independent accounts, each with balance and a position (idempotent)."""
    xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n<create>\n'
    for i in range(_ACCOUNT_COUNT):
        xml_str += generate_indent() + f'<account id="{_ACCOUNT_PREFIX}{i}" balance="10000000"/>\n'
    xml_str += generate_indent() + f'<symbol sym="{_SYMBOL}">\n'
    for i in range(_ACCOUNT_COUNT):
        xml_str += generate_indent(2) + f'<account id="{_ACCOUNT_PREFIX}{i}">100000</account>\n'
    xml_str += generate_indent() + '</symbol>\n</create>\n'
    return str(len(xml_str)) + "\n" + xml_str


def ensure_test_entities():
    """Send the setup request to the running server (safe to call multiple times)."""
    hostname = socket.gethostname()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.connect((hostname, 12345))
        send_xml_to_server(_setup_xml(), sock)
    except Exception as e:
        print(f"Warning: setup error (accounts may already exist): {e}")
    finally:
        sock.close()


# ---------------------------------------------------------------------------
# Request generators
# ---------------------------------------------------------------------------

def _random_request():
    """Generate a random buy/sell/query/cancel from a random account."""
    acct = f"{_ACCOUNT_PREFIX}{random.randint(0, _ACCOUNT_COUNT - 1)}"
    op = random.choice(['buy', 'sell', 'query', 'cancel'])
    xml_str = f'<?xml version="1.0" encoding="UTF-8"?>\n<transactions id="{acct}">\n'
    if op == 'buy':
        xml_str += generate_indent() + f'<order sym="{_SYMBOL}" amount="{random.randint(1, 100)}" limit="{random.uniform(10, 100):.2f}"/>\n'
    elif op == 'sell':
        xml_str += generate_indent() + f'<order sym="{_SYMBOL}" amount="-{random.randint(1, 10)}" limit="{random.uniform(10, 100):.2f}"/>\n'
    elif op == 'query':
        xml_str += generate_indent() + f'<query id="{random.randint(1, 500)}"/>\n'
    else:
        xml_str += generate_indent() + f'<cancel id="{random.randint(1, 500)}"/>\n'
    xml_str += '</transactions>\n'
    return str(len(xml_str)) + "\n" + xml_str


def _order_only_request():
    """Buy or sell only — used for latency measurement (same path as match-only timer)."""
    acct = f"{_ACCOUNT_PREFIX}{random.randint(0, _ACCOUNT_COUNT - 1)}"
    op = random.choice(['buy', 'sell'])
    xml_str = f'<?xml version="1.0" encoding="UTF-8"?>\n<transactions id="{acct}">\n'
    if op == 'buy':
        xml_str += generate_indent() + f'<order sym="{_SYMBOL}" amount="{random.randint(1, 100)}" limit="{random.uniform(10, 100):.2f}"/>\n'
    else:
        xml_str += generate_indent() + f'<order sym="{_SYMBOL}" amount="-{random.randint(1, 10)}" limit="{random.uniform(10, 100):.2f}"/>\n'
    xml_str += '</transactions>\n'
    return str(len(xml_str)) + "\n" + xml_str


# ---------------------------------------------------------------------------
# Measurement helpers
# ---------------------------------------------------------------------------

def _read_match_latencies():
    try:
        with open(MATCH_LATENCY_FILE, 'r') as f:
            return [float(line.strip()) for line in f if line.strip()]
    except (OSError, ValueError):
        return []


def _send_batch(request_count):
    """Worker: open one persistent connection and send request_count requests."""
    hostname = socket.gethostname()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.connect((hostname, 12345))
        for _ in range(request_count):
            send_xml_to_server(_random_request(), sock)
    except Exception as e:
        print(f"Error in batch worker: {e}")
    finally:
        sock.close()


def measure_throughput(request_count, thread_count=10):
    """Measure throughput with thread_count concurrent client connections."""
    print(f"    Throughput: {request_count} requests across {thread_count} clients...")
    start = time.time()
    threads = [
        threading.Thread(target=_send_batch, args=(request_count // thread_count,))
        for _ in range(thread_count)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.time() - start
    print(f"    Done in {elapsed:.2f}s")
    return request_count / elapsed


def measure_latency(request_count):
    """Measure per-request e2e latency (buy/sell only, one new TCP conn per request)."""
    hostname = socket.gethostname()
    latencies = []
    for _ in range(request_count):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.connect((hostname, 12345))
            req = _order_only_request()
            t0 = time.time()
            send_xml_to_server(req, sock)
            latencies.append(time.time() - t0)
        except Exception as e:
            print(f"Error measuring latency: {e}")
        finally:
            sock.close()
    if not latencies:
        return 0, 0
    return statistics.mean(latencies), statistics.stdev(latencies) if len(latencies) > 1 else 0


# ---------------------------------------------------------------------------
# Core test loop
# ---------------------------------------------------------------------------

def run_performance_test(core_counts, iterations=10):
    """Run throughput + latency tests for each core count."""
    results = {}
    ensure_test_entities()

    for cores in core_counts:
        set_core_count(cores)
        ensure_test_entities()

        throughputs, latencies, match_means = [], [], []
        for i in range(iterations):
            print(f"  [{cores} cores] iteration {i+1}/{iterations}")
            open(MATCH_LATENCY_FILE, 'w').close()

            tp = measure_throughput(500)
            avg_lat, _ = measure_latency(200)
            samples = _read_match_latencies()
            match_mean = statistics.mean(samples) if samples else 0

            throughputs.append(tp)
            latencies.append(avg_lat)
            match_means.append(match_mean)
            print(f"    throughput={tp:.2f} req/s  e2e={avg_lat:.6f}s  match={match_mean:.6f}s  ({len(samples)} match samples)")

        def _stats(vals):
            return statistics.mean(vals), (statistics.stdev(vals) if len(vals) > 1 else 0)

        avg_tp, sd_tp = _stats(throughputs)
        avg_lat, sd_lat = _stats(latencies)
        avg_match, sd_match = _stats(match_means)

        results[cores] = {
            "avg_throughput": avg_tp, "std_dev_throughput": sd_tp,
            "avg_latency": avg_lat, "std_dev_latency": sd_lat,
            "avg_match_latency": avg_match, "std_dev_match_latency": sd_match,
            "match_latency_n": iterations,
            "raw_throughputs": throughputs,
            "raw_avg_latencies": latencies,
            "raw_match_iter_means": match_means,
            "iterations": iterations,
        }
        print(f"  [{cores} cores] avg throughput={avg_tp:.2f} req/s  avg e2e={avg_lat:.6f}s  avg match={avg_match:.6f}s")

    generate_graph(results)
    return results


# ---------------------------------------------------------------------------
# Server management
# ---------------------------------------------------------------------------

def set_core_count(cores):
    print(f"Setting server to use {cores} cores...")
    try:
        result = subprocess.run(["lsof", "-i", ":12345", "-t"], capture_output=True, text=True)
        if result.stdout.strip():
            pids = result.stdout.split()
            print(f"Killing existing server process(es): {', '.join(pids)}...")
            subprocess.run(["kill", *pids], check=False)
            time.sleep(2)
    except Exception as e:
        print(f"Warning: could not kill existing server: {e}")

    server_env = os.environ.copy()
    server_env["CPU_CORES"] = str(cores)
    server_env["MATCH_LATENCY_FILE"] = MATCH_LATENCY_FILE
    server_path = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "server.py"))
    subprocess.Popen([sys.executable, server_path], env=server_env,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3)
    print(f"Server restarted with {cores} cores")


# ---------------------------------------------------------------------------
# Graphs
# ---------------------------------------------------------------------------

def generate_graph(results):
    cores = sorted(results.keys())
    n = results[cores[0]]["iterations"] if cores else 0

    def _se(c, sd_key, n_key="iterations"):
        n_val = results[c][n_key]
        return results[c][sd_key] / (n_val ** 0.5) if n_val > 0 else 0

    def _scatter(ax, vals_key, color, jitter=0.12):
        for c in cores:
            vals = results[c].get(vals_key, [])
            if not vals:
                continue
            offsets = [(-jitter + 2 * jitter * k / (len(vals) - 1)) for k in range(len(vals))] if len(vals) > 1 else [0.0]
            ax.scatter([c + d for d in offsets], vals, color=color, s=25, alpha=0.65)

    # Throughput
    fig, ax = plt.subplots(figsize=(10, 6))
    _scatter(ax, "raw_throughputs", "#a5d6a7")
    ax.errorbar(cores, [results[c]["avg_throughput"] for c in cores],
                yerr=[_se(c, "std_dev_throughput") for c in cores],
                fmt='s-', capsize=5, linewidth=2, color='#2e7d32', label=f'Mean ± SE (n={n})')
    ax.set_xlabel("Number of Cores")
    ax.set_ylabel("Throughput (requests/second)")
    ax.set_title("Throughput vs Number of Cores\n(50-account realistic workload)")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig("writeup/throughput_vs_cores.png", dpi=180)
    plt.close(fig)

    # E2E latency
    fig, ax = plt.subplots(figsize=(10, 6))
    _scatter(ax, "raw_avg_latencies", "#ffcdd2")
    ax.errorbar(cores, [results[c]["avg_latency"] for c in cores],
                yerr=[_se(c, "std_dev_latency") for c in cores],
                fmt='o-', capsize=5, linewidth=2, color='r', label=f'Mean ± SE (n={n})')
    ax.set_xlabel("Number of Cores")
    ax.set_ylabel("End-to-End Latency (seconds)")
    ax.set_title("End-to-End Latency vs Number of Cores\n(client round-trip: TCP + parse + DB + match)")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig("writeup/latency_vs_cores.png", dpi=180)
    plt.close(fig)

    # Match-only latency
    fig, ax = plt.subplots(figsize=(10, 6))
    _scatter(ax, "raw_match_iter_means", "#ffccbc")
    ax.errorbar(cores, [results[c]["avg_match_latency"] for c in cores],
                yerr=[_se(c, "std_dev_match_latency", "match_latency_n") for c in cores],
                fmt='s-', capsize=5, linewidth=2, color='#e65100', label=f'Mean ± SE (n={n})')
    ax.set_xlabel("Number of Cores")
    ax.set_ylabel("Matching Engine Latency (seconds)")
    ax.set_title("Pure Matching Engine Latency vs Number of Cores\n(server-side: order-book query + execution only)")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig("writeup/matching_latency_vs_cores.png", dpi=180)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Network helper
# ---------------------------------------------------------------------------

def send_xml_to_server(xml_request, client_socket, timeout=2):
    client_socket.settimeout(timeout)
    try:
        client_socket.sendall(xml_request.encode('utf-8'))
        return client_socket.recv(4096).decode('utf-8', errors='replace')
    except socket.timeout:
        return "<results><e>Request timed out</e></results>"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

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

    print(f"System has {available_cores} available cores, testing: {core_counts}")
    try:
        results = run_performance_test(core_counts)
        print("\nSummary:")
        for c, d in results.items():
            print(f"  {c} cores: throughput={d['avg_throughput']:.2f} ±{d['std_dev_throughput']:.2f} req/s"
                  f"  e2e={d['avg_latency']:.6f} ±{d['std_dev_latency']:.6f}s"
                  f"  match={d['avg_match_latency']:.6f}s")
    except Exception as e:
        print(f"Performance test failed: {e}")
