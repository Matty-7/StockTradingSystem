import socket
from database import Database
from xml_handler import XMLHandler
from matching_engine import MatchingEngine
import os
import logging
import time
import signal
import selectors
import sys
import threading
import psutil
import psycopg2
import psycopg2.extensions
from urllib.parse import urlparse, urlunparse

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
def _mask_db_url(url: str) -> str:
    try:
        parsed = urlparse(url)
        if parsed.password:
            masked = parsed._replace(netloc=f"{parsed.username}:***@{parsed.hostname}"
                                     + (f":{parsed.port}" if parsed.port else ""))
            return urlunparse(masked)
    except Exception:
        pass
    return "<db_url>"

logger.info(f"Database URL: {_mask_db_url(db_url)}")

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
                        p = psutil.Process(os.getpid())
                        if hasattr(p, 'cpu_affinity'):
                            try:
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
    
    def _start_order_book_listener(self, matching_engine):
        """Start a background thread that listens for new_order NOTIFY events.

        When another worker places an order with open shares, it broadcasts the
        order details via pg_notify('new_order', payload).  This thread receives
        those notifications and inserts the order into the local in-memory book,
        eliminating the DB fallback scan for cross-worker orders.

        Payload format: "<order_id>,<is_buy>,<price>,<created_at_iso>"
        """
        def _listen():
            import datetime
            try:
                conn = psycopg2.connect(self.db_url)
                conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
                cur = conn.cursor()
                cur.execute("LISTEN new_order;")
                logger.info(f"Worker {os.getpid()} listening on 'new_order' channel")
                while self.running:
                    if not self.running:
                        break
                    # Poll with 1-second timeout so we can check self.running
                    import select as _select
                    readable, _, _ = _select.select([conn], [], [], 5.0)
                    if readable:
                        conn.poll()
                        while conn.notifies:
                            notify = conn.notifies.pop(0)
                            try:
                                parts = notify.payload.split(",", 3)
                                order_id = int(parts[0])
                                is_buy = parts[1] == "1"
                                price = float(parts[2])
                                created_at = datetime.datetime.fromisoformat(parts[3])
                                matching_engine.order_book._insert(order_id, price, created_at, is_buy)
                            except Exception as e:
                                logger.warning(f"Failed to parse new_order notify payload '{notify.payload}': {e}")
            except Exception as e:
                logger.error(f"Order book listener thread error: {e}")
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

        t = threading.Thread(target=_listen, daemon=True)
        t.start()
        return t

    def worker_process_connections(self):
        """Worker process accepts and handles connections"""
        # Create database connection
        database = Database(self.db_url)
        matching_engine = MatchingEngine(database)
        with database.session_scope() as session:
            matching_engine.load_order_book(session)
        xml_handler = XMLHandler(database, matching_engine)

        # Start background thread to receive cross-worker order book updates.
        self._start_order_book_listener(matching_engine)
        
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
        """Handle a client connection with buffered reads.

        The original implementation called recv(1) in a loop to read the
        length prefix, triggering one kernel syscall per byte.  For a typical
        4-byte length like "173\n" that is 4 unnecessary context switches per
        request.  This version reads in 64-byte chunks and splits on '\\n',
        collapsing the header read to a single syscall in the common case.

        A persistent bytearray buffer is kept across requests on the same
        connection so any bytes read beyond the current message are used for
        the next one (handles TCP coalescing / pipelined requests).
        """
        # Disable Nagle's algorithm so each sendall() goes out immediately
        # without the OS waiting to accumulate more data into a larger segment.
        client_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        buf = bytearray()
        try:
            while True:
                # --- Phase 1: read until \n to get the message length ---
                while b"\n" not in buf:
                    chunk = client_socket.recv(64)
                    if not chunk:
                        logger.info(f"Client {address} disconnected.")
                        return
                    buf += chunk

                newline_pos = buf.index(b"\n")
                length_bytes = bytes(buf[:newline_pos])
                buf = buf[newline_pos + 1:]

                if not length_bytes:
                    logger.info(f"Client {address} sent empty length line, closing.")
                    return

                try:
                    message_length = int(length_bytes.decode('utf-8'))
                    logger.debug(f"Message length {message_length} from {address}")
                except ValueError:
                    logger.warning(f"Invalid length from {address}: {length_bytes!r}")
                    try:
                        client_socket.sendall(b"<results><error>Invalid message length</error></results>")
                    except Exception:
                        pass
                    continue

                # --- Phase 2: read exactly message_length bytes ---
                while len(buf) < message_length:
                    chunk = client_socket.recv(min(4096, message_length - len(buf)))
                    if not chunk:
                        logger.warning(f"Client {address} disconnected mid-message "
                                       f"({len(buf)}/{message_length} bytes received).")
                        return
                    buf += chunk

                xml_data = bytes(buf[:message_length])
                buf = buf[message_length:]

                # --- Phase 3: process and respond ---
                try:
                    logger.info(f"Processing XML from {address} ({message_length} bytes)")
                    response = xml_handler.process_request(xml_data.decode('utf-8'))
                    client_socket.sendall(response.encode('utf-8'))
                    logger.info(f"Response sent to {address}")
                except UnicodeDecodeError as e:
                    logger.error(f"Non-UTF-8 payload from {address}: {e}")
                    try:
                        client_socket.sendall(b"<results><error>Invalid UTF-8 in XML</error></results>")
                    except Exception:
                        pass
                except Exception as e:
                    logger.exception(f"Error processing request from {address}: {e}")
                    try:
                        client_socket.sendall(b"<results><error>Internal server error</error></results>")
                    except Exception:
                        pass
                    return

        except ConnectionResetError:
            logger.warning(f"Connection reset by {address}")
        except Exception as e:
            logger.exception(f"Unhandled error for client {address}: {e}")
        finally:
            logger.info(f"Closing connection for {address}")
            client_socket.close()
    
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
