import subprocess
import os
import time
import argparse

def run_all_tests():
    """Run all functional and performance tests"""
    print("Starting comprehensive tests...")
    
    # Get current path and project root path
    current_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(current_dir)
    
    # 1. Start server (using absolute path)
    server_path = os.path.join(root_dir, "server.py")
    print(f"Starting server: {server_path}")
    server_process = subprocess.Popen(["python3", server_path])
    time.sleep(2)  # Wait for server to start
    
    try:
        # 2. Run functional tests (fix file name and path)
        print("\n=== Running Functional Tests ===")
        client_path = os.path.join(current_dir, "client.py")
        if os.path.exists(client_path):
            subprocess.run(["python3", client_path], check=True)
        else:
            print(f"Warning: Functional test file not found: {client_path}")
            # Try alternative file name
            alt_client_path = os.path.join(current_dir, "client_test.py")
            if os.path.exists(alt_client_path):
                print(f"Using alternative file: {alt_client_path}")
                subprocess.run(["python3", alt_client_path], check=True)
            else:
                print(f"Error: Client test file not found")
        
        # 3. Run edge case tests
        print("\n=== Running Edge Case Tests ===")
        edge_cases_path = os.path.join(current_dir, "edge_cases_test.py")
        if os.path.exists(edge_cases_path):
            subprocess.run(["python3", edge_cases_path], check=True)
        else:
            print(f"Warning: Edge case test file not found: {edge_cases_path}")
        
        # 4. Run concurrency tests
        print("\n=== Running Concurrency Tests ===")
        concurrency_path = os.path.join(current_dir, "concurrency_test.py")
        if os.path.exists(concurrency_path):
            subprocess.run(["python3", concurrency_path], check=True)
        else:
            print(f"Warning: Concurrency test file not found: {concurrency_path}")
        
        # 5. Run performance and scalability tests
        print("\n=== Running Performance and Scalability Tests ===")
        performance_path = os.path.join(current_dir, "performance_test.py")
        if os.path.exists(performance_path):
            subprocess.run(["python3", performance_path], check=True)
        else:
            print(f"Warning: Performance test file not found: {performance_path}")
        
    except Exception as e:
        print(f"Error occurred during testing: {e}")
    finally:
        # Shut down server
        print("Shutting down server...")
        server_process.terminate()
        server_process.wait(timeout=5)
    
    print("\nAll tests completed!")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run all exchange engine tests")
    parser.add_argument("--cores", type=int, default=None, 
                       help="Specify number of cores to use for testing")
    args = parser.parse_args()
    
    if args.cores:
        os.environ["CPU_CORES"] = str(args.cores)
    
    run_all_tests()
