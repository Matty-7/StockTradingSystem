import socket
import threading
import xml.etree.ElementTree as ET
from database import Database
from xml_handler import XMLHandler
from matching_engine import MatchingEngine
import os

# Initialize global instances
db_url = os.environ.get('DATABASE_URL', 'postgresql://username:password@localhost/exchange')
database = Database(db_url)
matching_engine = MatchingEngine(database)
xml_handler = XMLHandler(database, matching_engine)

def handle_client(client_socket, address):
    """Handle a client connection, allowing multiple requests."""
    try:
        while True:  # Keep reading requests from the client
            length_str = b""
            char = client_socket.recv(1)
            while char != b"\n" and char != b"":
                length_str += char
                char = client_socket.recv(1)

            if not length_str:
                break  # Client closed connection

            try:
                message_length = int(length_str.decode('utf-8'))
            except ValueError:
                client_socket.sendall(b"Error: Invalid message length\n")
                continue  # Allow next request

            xml_data = b""
            bytes_read = 0
            while bytes_read < message_length:
                chunk = client_socket.recv(min(4096, message_length - bytes_read))
                if not chunk:
                    break
                xml_data += chunk
                bytes_read += len(chunk)

            if bytes_read < message_length:
                client_socket.sendall(b"Error: Incomplete message\n")
                continue  # Allow next request

            # Process XML
            response = xml_handler.process_request(xml_data.decode('utf-8'))

            # Send response
            client_socket.sendall(response.encode('utf-8'))

    except Exception as e:
        print(f"Error handling client {address}: {e}")
    finally:
        client_socket.close()  # Close after client disconnects


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
