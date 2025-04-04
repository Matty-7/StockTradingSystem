import socket
import threading
import xml.etree.ElementTree as ET
from database import Database
from xml_handler import XMLHandler
from matching_engine import MatchingEngine
import os
import logging
import time
import multiprocessing
import signal
import selectors
import sys
import psutil

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    handlers=[logging.StreamHandler()])
logger = logging.getLogger(__name__)

# Configure number of worker processes based on CPU cores
NUM_WORKERS = os.cpu_count() or 4  # Default to 4 if cpu_count is None
if 'CPU_CORES' in os.environ:
    try:
        NUM_WORKERS = int(os.environ['CPU_CORES'])
    except ValueError:
        pass  # Use the default if the environment variable is not a valid integer

logger.info(f"Configuring server with {NUM_WORKERS} worker processes")

# Database connection information
db_url = os.environ.get('DATABASE_URL', 'postgresql://username:password@localhost/exchange')
logger.info(f"Database URL: {db_url}")

class PreForkServer:
    """Pre-fork server model with shared server socket across processes"""
    
    def __init__(self, host, port, num_workers, db_url):
        self.host = host
        self.port = port
        self.num_workers = num_workers
        self.db_url = db_url
        self.workers = []
        self.server_socket = None
        self.running = True
        
    def setup_socket(self):
        """Create and set up server socket"""
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # Set non-blocking mode for accept
        self.server_socket.setblocking(False)
        # Bind to port
        self.server_socket.bind((self.host, self.port))
        # Start listening
        self.server_socket.listen(128)  # Increased backlog for high-load scenarios
        logger.info(f"Server socket listening on {self.host}:{self.port}")
    
    def prefork_workers(self):
        """Fork worker processes"""
        for i in range(self.num_workers):
            # Create child process
            pid = os.fork()
            if pid == 0:
                # Child process
                logger.info(f"Worker process {os.getpid()} started")
                # Ensure it only uses one CPU core if we're doing CPU affinity
                if self.num_workers <= psutil.cpu_count():
                    try:
                        # Set CPU affinity - each worker to a specific core
                        p = psutil.Process(os.getpid())
                        p.cpu_affinity([i % psutil.cpu_count()])
                        logger.info(f"Worker {os.getpid()} assigned to CPU core {i % psutil.cpu_count()}")
                    except Exception as e:
                        logger.warning(f"Failed to set CPU affinity: {e}")
                
                # Handle connections in worker
                self.worker_process_connections()
                sys.exit(0)  # Child exits after worker_process_connections returns
            else:
                # Parent process
                self.workers.append(pid)
        
        logger.info(f"Pre-forked {self.num_workers} worker processes: {self.workers}")
    
    def worker_process_connections(self):
        """Worker process accepts and handles connections"""
        # Create database connection
        database = Database(self.db_url)
        matching_engine = MatchingEngine(database)
        xml_handler = XMLHandler(database, matching_engine)
        
        # Set up selector to monitor the server socket
        selector = selectors.DefaultSelector()
        selector.register(self.server_socket, selectors.EVENT_READ)
        
        # Main loop for accepting connections
        while self.running:
            # Use select to avoid blocking indefinitely
            events = selector.select(timeout=1.0)
            if not events and not self.running:
                break
                
            for key, _ in events:
                if key.fileobj is self.server_socket:
                    try:
                        client_socket, address = self.server_socket.accept()
                        client_socket.setblocking(True)  # Set back to blocking mode for client handling
                        logger.info(f"Worker {os.getpid()} accepted connection from {address}")
                        
                        # Handle client
                        self.handle_client(client_socket, address, xml_handler)
                    except BlockingIOError:
                        # No connection available, just continue
                        continue
                    except Exception as e:
                        logger.error(f"Error accepting connection: {e}")
        
        # Clean up
        selector.close()
        logger.info(f"Worker {os.getpid()} shutting down")
    
    def handle_client(self, client_socket, address, xml_handler):
        """Handle a client connection, allowing multiple requests.""" 
        try:
            while True:  # Keep reading requests from the client
                length_str = b""
                try:
                    char = client_socket.recv(1)
                    while char != b"\n" and char != b"":
                        length_str += char
                        char = client_socket.recv(1)
                except ConnectionResetError:
                    logger.warning(f"Client {address} closed connection unexpectedly while reading length.")
                    break
                except Exception as e:
                    logger.error(f"Error receiving length from {address}: {e}")
                    break

                if not length_str:
                    logger.info(f"Client {address} disconnected gracefully (empty length).")
                    break  # Client closed connection

                try:
                    message_length = int(length_str.decode('utf-8'))
                    logger.debug(f"Received message length {message_length} from {address}")
                except ValueError:
                    error_msg = b"Error: Invalid message length format\n"
                    logger.warning(f"Invalid message length received from {address}: {length_str.decode('utf-8', errors='ignore')}")
                    try:
                        client_socket.sendall(error_msg)
                    except Exception as send_e:
                         logger.error(f"Error sending invalid length error to {address}: {send_e}")
                    continue  # Allow next request
                except Exception as e:
                     logger.error(f"Error processing message length from {address}: {e}")
                     break # Unexpected error, close connection

                xml_data = b""
                bytes_read = 0
                try:
                    while bytes_read < message_length:
                        # Read in chunks, but handle potential partial reads
                        chunk = client_socket.recv(min(4096, message_length - bytes_read))
                        if not chunk:
                            logger.warning(f"Client {address} disconnected before sending full message (expected {message_length}, got {bytes_read}).")
                            break # Connection closed prematurely
                        xml_data += chunk
                        bytes_read += len(chunk)
                        logger.debug(f"Read chunk from {address}, total bytes: {bytes_read}/{message_length}")

                    if bytes_read < message_length:
                        logger.warning(f"Incomplete message received from {address} (expected {message_length}, got {bytes_read}).")
                        # Depending on requirements, you might try to process partial data or just discard
                        continue # Or break, depending on how partial requests should be handled

                    # Process XML - using process-local XML handler
                    logger.info(f"Processing XML request from {address} (length: {message_length})")
                    response = xml_handler.process_request(xml_data.decode('utf-8'))

                    # Send response
                    logger.debug(f"Sending response to {address}: {response[:200]}...")
                    client_socket.sendall(response.encode('utf-8'))
                    logger.info(f"Response sent to {address}")

                except ConnectionResetError:
                     logger.warning(f"Client {address} closed connection unexpectedly during message read/process.")
                     break
                except UnicodeDecodeError as ude:
                    logger.error(f"XML data from {address} is not valid UTF-8: {ude}")
                    try:
                        client_socket.sendall(b"<results><error>Invalid UTF-8 encoding in XML</error></results>")
                    except Exception as send_e:
                        logger.error(f"Error sending UTF-8 error to {address}: {send_e}")
                    continue # Allow next request, maybe?
                except Exception as e:
                    logger.exception(f"Error handling client {address} during message read/process: {e}")
                    # Attempt to send a generic error response if the socket is still usable
                    try:
                        client_socket.sendall(b"<results><error>Internal server error</error></results>")
                    except Exception as send_e:
                        logger.error(f"Error sending generic error to {address} after exception: {send_e}")
                    break # Close connection on unexpected processing errors

        except Exception as e:
            # Catch exceptions occurring outside the main loop (e.g., during initial recv)
            logger.exception(f"Unhandled error for client {address}: {e}")
        finally:
            logger.info(f"Closing connection for client {address}")
            client_socket.close()  # Ensure socket is closed
    
    def signal_handler(self, sig, frame):
        """Handle signals to gracefully shut down the server"""
        if sig == signal.SIGINT or sig == signal.SIGTERM:
            logger.info(f"Received signal {sig}, shutting down server...")
            self.running = False
            # Stop accepting new connections
            if self.server_socket:
                self.server_socket.close()
            
            # Send signal to child processes
            for pid in self.workers:
                try:
                    logger.info(f"Sending signal to worker process {pid}")
                    os.kill(pid, signal.SIGTERM)
                except OSError as e:
                    logger.error(f"Error sending signal to process {pid}: {e}")
            
            # Wait for workers to exit
            logger.info("Waiting for worker processes to exit...")
            for _ in range(5):  # Try up to 5 seconds
                if not self.workers:
                    break
                for pid in list(self.workers):
                    try:
                        pid, status = os.waitpid(pid, os.WNOHANG)
                        if pid:
                            logger.info(f"Worker process {pid} exited with status {status}")
                            self.workers.remove(pid)
                    except OSError:
                        self.workers.remove(pid)
                time.sleep(1)
            
            # Force kill any remaining workers
            for pid in self.workers:
                try:
                    logger.warning(f"Force killing worker process {pid}")
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass
            
            logger.info("Server shutdown complete")
            sys.exit(0)
    
    def run(self):
        """Run the server"""
        # Setup signal handling
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        
        # Setup server socket
        self.setup_socket()
        
        # Create worker processes
        self.prefork_workers()
        
        # Main process just waits for signals and monitors workers
        try:
            logger.info("Main server process waiting for signals...")
            while self.running:
                # Check if any workers died and restart them
                for pid in list(self.workers):
                    try:
                        # Check if process is still alive (non-blocking)
                        result_pid, status = os.waitpid(pid, os.WNOHANG)
                        if result_pid:
                            logger.warning(f"Worker process {pid} exited unexpectedly with status {status}")
                            self.workers.remove(pid)
                            # Fork a new worker to replace it
                            new_pid = os.fork()
                            if new_pid == 0:
                                # New child process
                                logger.info(f"Replacement worker process {os.getpid()} started")
                                # Handle connections in worker
                                self.worker_process_connections()
                                sys.exit(0)
                            else:
                                # Parent process
                                self.workers.append(new_pid)
                                logger.info(f"Started replacement worker process: {new_pid}")
                    except OSError:
                        # Process doesn't exist anymore
                        if pid in self.workers:
                            self.workers.remove(pid)
                
                time.sleep(1)  # Sleep to avoid busy waiting
        except KeyboardInterrupt:
            # Handle Ctrl+C gracefully (although signal handler should catch this)
            logger.info("Received keyboard interrupt, shutting down...")
            self.running = False
        finally:
            # Final cleanup
            if self.server_socket:
                self.server_socket.close()
            
            logger.info("Server shut down")

def main():
    # Start pre-fork server
    server = PreForkServer('0.0.0.0', 12345, NUM_WORKERS, db_url)
    print(f"Exchange server started on port 12345 with {NUM_WORKERS} worker processes...")
    server.run()

if __name__ == "__main__":
    main()
