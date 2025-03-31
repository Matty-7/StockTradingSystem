import string
import socket
import xml.etree.ElementTree as ET
import xml.dom.minidom
import io
import time

def generate_indent(level=1):
  """
  generates a string containing level number of indents.
  """
  return '  ' * level

def basic_creation_test():
  """
  171
  <?xml version="1.0" encoding="UTF-8"?>
  <create>
  <account id="123456" balance="1000"/>
    <symbol sym="SPY">
      <account id="123456">100000</account>
    </symbol>
  </create>
  """
  xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n'
  xml_str += '<create>\n'
  xml_str += generate_indent() +'<account id="123456" balance="1000"/>\n'
  xml_str += generate_indent() + '<symbol sym="SPY">\n'
  xml_str += generate_indent(2)+'<account id="123456">100000</account>\n'
  xml_str += generate_indent()+ '</symbol>\n'
  xml_str += '</create>\n'

  return  str(len(xml_str)) + "\n" + xml_str

def basic_order_transaction_test():
  """
  131
  <?xml version="1.0" encoding="UTF-8"?>
  <transactions id="123456">
    <order sym="SPY" amount="100" limit="145.67"/>
  </transactions>
  """
  xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n'
  xml_str += '<transactions id="123456">\n'
  xml_str += generate_indent() + '<order sym="SPY" amount="100" limit="145.67"/>\n'
  xml_str += '</transactions>\n'

  return  str(len(xml_str)) + "\n" + xml_str

def main():
    #Server address
    hostname = socket.gethostname()
    server_address = (hostname, 12345)

    # Create the socket
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    
    try:
        client_socket.connect(server_address)
        print(f"Connected to server at {server_address}")

        #Send XML to create an accoutn and a symbol. Should return an created tag for both.
        #Expected : <results><created id="123456"/><created sym="SPY" id="123456"/></results>
        xml_request = basic_creation_test()
        client_socket.sendall(xml_request.encode('utf-8'))
        print(f"Sent request:\n{xml_request}")
        response = client_socket.recv(4096)
        print(f"Server response:\n{response.decode('utf-8')}")

        #Send XML to create an accoutn and a symbol. Should return an created tag for both.
        #Expected : <results><created id="123456"/><created sym="SPY" id="123456"/></results>
        xml_request = basic_creation_test()
        client_socket.sendall(xml_request.encode('utf-8'))
        print(f"Sent request:\n{xml_request}")
        response = client_socket.recv(4096)
        print(f"Server response:\n{response.decode('utf-8')}")

        #Send XML to make an order transaction.
        # should respond with results and an opened
        xml_request = basic_order_transaction_test()
        client_socket.sendall(xml_request.encode('utf-8'))
        print(f"Sent request:\n{xml_request}")
        response = client_socket.recv(4096)
        print(f"Server response:\n{response.decode('utf-8')}")

    except Exception as e:
        print(f"Error: {e}")

    finally:
        # Close the connection
        client_socket.close()

if __name__ == "__main__":
    main()
