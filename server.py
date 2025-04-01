import socket
import threading
import xml.etree.ElementTree as ET
from database import Database
from xml_handler import XMLHandler
from matching_engine import MatchingEngine
import os
import logging # Import logging

# Configure basic logging
logging.basicConfig(level=logging.INFO, # Change to DEBUG for more verbose output
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    handlers=[logging.StreamHandler()]) # Log to console
logger = logging.getLogger(__name__)

# Initialize global instances
db_url = os.environ.get('DATABASE_URL', 'postgresql://username:password@localhost/exchange')
logger.info(f"Database URL: {db_url}")
database = Database(db_url)
matching_engine = MatchingEngine(database)
xml_handler = XMLHandler(database, matching_engine)

def handle_client(client_socket, address):
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

                # Process XML
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


def main():
    # Create server socket
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    # Bind to port
    server.bind(('0.0.0.0', 12345))

    # Start listening
    server.listen(5)
    print("Exchange server started, listening on port 12345...")

    try:
        while True:
            # Accept client connection
            client, address = server.accept()
            print(f"Accepted connection from {address}")

            # Create a new thread for each client
            client_handler = threading.Thread(target=handle_client, args=(client, address))
            client_handler.daemon = True
            client_handler.start()
    except KeyboardInterrupt:
        print("Server shutting down")
    finally:
        server.close()

if __name__ == "__main__":
    main()
