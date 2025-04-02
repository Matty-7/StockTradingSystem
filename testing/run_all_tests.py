import subprocess
import os
import time
import argparse
import io
import sys
from datetime import datetime

def run_all_tests():
    """Run all functional and performance tests"""
    # Get timestamp for this test run
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Get current path and project root path
    current_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(current_dir)
    
    # Prepare results file
    writeup_dir = os.path.join(root_dir, "writeup")
    if not os.path.exists(writeup_dir):
        os.makedirs(writeup_dir)
    
    results_file = os.path.join(writeup_dir, f"run_all_tests_results.txt")
    
    # Open the results file to write all output
    with open(results_file, 'w') as f:
        f.write(f"Test Run: {timestamp}\n")
        f.write("=" * 80 + "\n\n")
        
        print("Starting comprehensive tests...")
        f.write("Starting comprehensive tests...\n")
        
        # 1. Start server (using absolute path)
        server_path = os.path.join(root_dir, "server.py")
        print(f"Starting server: {server_path}")
        f.write(f"Starting server: {server_path}\n")
        
        server_process = subprocess.Popen(["python3", server_path], 
                                         stdout=subprocess.PIPE, 
                                         stderr=subprocess.STDOUT,
                                         text=True)
        time.sleep(2)  # Wait for server to start
        
        try:
            # 2. Run functional tests (fix file name and path)
            print("\n=== Running Functional Tests ===")
            f.write("\n=== Running Functional Tests ===\n")
            
            client_path = os.path.join(current_dir, "client.py")
            if os.path.exists(client_path):
                result = subprocess.run(["python3", client_path], 
                                      capture_output=True, 
                                      text=True)
                print(result.stdout)
                f.write(result.stdout)
                if result.stderr:
                    print(result.stderr)
                    f.write(result.stderr)
            else:
                msg = f"Warning: Functional test file not found: {client_path}"
                print(msg)
                f.write(msg + "\n")
                
                # Try alternative file name
                alt_client_path = os.path.join(current_dir, "client_test.py")
                if os.path.exists(alt_client_path):
                    msg = f"Using alternative file: {alt_client_path}"
                    print(msg)
                    f.write(msg + "\n")
                    
                    result = subprocess.run(["python3", alt_client_path], 
                                          capture_output=True, 
                                          text=True)
                    print(result.stdout)
                    f.write(result.stdout)
                    if result.stderr:
                        print(result.stderr)
                        f.write(result.stderr)
                else:
                    msg = "Error: Client test file not found"
                    print(msg)
                    f.write(msg + "\n")
            
            # 3. Run edge case tests
            print("\n=== Running Edge Case Tests ===")
            f.write("\n=== Running Edge Case Tests ===\n")
            
            edge_cases_path = os.path.join(current_dir, "edge_cases_test.py")
            if os.path.exists(edge_cases_path):
                result = subprocess.run(["python3", edge_cases_path], 
                                      capture_output=True, 
                                      text=True)
                print(result.stdout)
                f.write(result.stdout)
                if result.stderr:
                    print(result.stderr)
                    f.write(result.stderr)
            else:
                msg = f"Warning: Edge case test file not found: {edge_cases_path}"
                print(msg)
                f.write(msg + "\n")
            
            # 4. Run concurrency tests
            print("\n=== Running Concurrency Tests ===")
            f.write("\n=== Running Concurrency Tests ===\n")
            
            concurrency_path = os.path.join(current_dir, "concurrency_test.py")
            if os.path.exists(concurrency_path):
                result = subprocess.run(["python3", concurrency_path], 
                                      capture_output=True, 
                                      text=True)
                print(result.stdout)
                f.write(result.stdout)
                if result.stderr:
                    print(result.stderr)
                    f.write(result.stderr)
            else:
                msg = f"Warning: Concurrency test file not found: {concurrency_path}"
                print(msg)
                f.write(msg + "\n")
            
            # 5. Run performance and scalability tests
            print("\n=== Running Performance and Scalability Tests ===")
            f.write("\n=== Running Performance and Scalability Tests ===\n")
            
            performance_path = os.path.join(current_dir, "performance_test.py")
            if os.path.exists(performance_path):
                result = subprocess.run(["python3", performance_path], 
                                      capture_output=True, 
                                      text=True)
                print(result.stdout)
                f.write(result.stdout)
                if result.stderr:
                    print(result.stderr)
                    f.write(result.stderr)
            else:
                msg = f"Warning: Performance test file not found: {performance_path}"
                print(msg)
                f.write(msg + "\n")
            
        except Exception as e:
            error_msg = f"Error occurred during testing: {e}"
            print(error_msg)
            f.write(error_msg + "\n")
            
        finally:
            # Collect server output
            server_output, _ = server_process.communicate()
            if server_output:
                print("Server output:")
                print(server_output)
                f.write("\n=== Server Output ===\n")
                f.write(server_output)
            
            # Shut down server
            print("Shutting down server...")
            f.write("\nShutting down server...\n")
            server_process.terminate()
            server_process.wait(timeout=5)
        
        print("\nAll tests completed!")
        f.write("\nAll tests completed!\n")
        
        print(f"\nTest results saved to: {results_file}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run all exchange engine tests")
    parser.add_argument("--cores", type=int, default=None, 
                       help="Specify number of cores to use for testing")
    args = parser.parse_args()
    
    if args.cores:
        os.environ["CPU_CORES"] = str(args.cores)
    
    run_all_tests()
