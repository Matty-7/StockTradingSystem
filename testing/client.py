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
  173
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
  xml_str += generate_indent()  + '<account id="123456" balance="1000"/>\n'
  xml_str += generate_indent()  + '<symbol sym="SPY">\n'
  xml_str += generate_indent(2) + '<account id="123456">100000</account>\n'
  xml_str += generate_indent()  + '</symbol>\n'
  xml_str += '</create>\n'

  return  str(len(xml_str)) + "\n" + xml_str

def test_empty_create():
  """
  58
  <?xml version="1.0" encoding="UTF-8"?>
  <create>
  </create>
  """
  xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n'
  xml_str += '<create>\n'
  xml_str += '</create>\n'

  return  str(len(xml_str)) + "\n" + xml_str

def test_create_symbol_error_account_DNE():
  """
  134
  <?xml version="1.0" encoding="UTF-8"?>
  <create>
    <symbol sym="SPY">
      <account id="9999999">100000</account>
    </symbol>
  </create>
  """
  xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n'
  xml_str += '<create>\n'
  xml_str += generate_indent()  + '<symbol sym="SPY">\n'
  xml_str += generate_indent(2) + '<account id="9999999">100000</account>\n'
  xml_str += generate_indent()  + '</symbol>\n'
  xml_str += '</create>\n'

  return  str(len(xml_str)) + "\n" + xml_str

def test_transaction_DNE():
  """
  129
  <?xml version="1.0" encoding="UTF-8"?>
  <transactions id="9999999">
    <order sym="SPY" amount="300" limit="125"/>
  </transactions>
  """
  xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n'
  xml_str += '<transactions id="9999999">\n'
  xml_str += generate_indent()  + '<order sym="SPY" amount="300" limit="125"/>\n'       # Account does not exist
  xml_str += '</transactions>\n'

  return  str(len(xml_str)) + "\n" + xml_str

def test_transaction_symbol_error_and_short_error():
  """
  176
  <?xml version="1.0" encoding="UTF-8"?>
  <transactions id="9999999">
    <order sym="DNE" amount"1" limit="1"/>
    <order sym="SPY" amount="-99999999" limit="100"/>
  </transactions>
  """
  xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n'
  xml_str += '<transactions id="9999999">\n'
  xml_str += generate_indent()  + '<order sym="DNE" amount"1" limit="1"/>\n'            # Symbol does not exist
  xml_str += generate_indent()  + '<order sym="SPY" amount="-99999999" limit="100"/>\n' # short which is not allowed for assignment
  xml_str += '</transactions>\n'

  return str(len(xml_str)) + "\n" + xml_str

def test_transaction_errors():
  send_xml_to_server(test_transaction_DNE())
  send_xml_to_server(test_transaction_symbol_error_and_short_error())

def setup_test_transcation_matching():
  """
  132
  <?xml version="1.0" encoding="UTF-8"?>
  <create>
    <account id="1" balance="100000"/>
    <account id="2" balance="100000"/>
  </create>
  """
  xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n'
  xml_str += '<create>\n'
  xml_str += generate_indent()  + '<account id="1" balance="1000000"/>\n'
  xml_str += generate_indent()  + '<account id="2" balance="1000000"/>\n'
  xml_str += generate_indent()  + '<symbol sym="AMZN">\n'
  xml_str += generate_indent(2) + '<account id="2">100000</account>\n'
  xml_str += generate_indent()  + '</symbol>\n'
  xml_str += '</create>\n'

  return  str(len(xml_str)) + "\n" + xml_str

def test_transaction_matching1():
  """
  227
  <?xml version="1.0" encoding="UTF-8"?>
  <transactions id="1">
    <order sym="AMZN" amount="300" limit="125"/>
    <order sym="AMZN" amount="200" limit="127"/>
    <order sym="AMZN" amount="400" limit="125"/>
  </transactions>
  """
  xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n'
  xml_str += '<transactions id="1">\n'
  xml_str += generate_indent()  + '<order sym="AMZN" amount="300" limit="125"/>\n'  #status id=1
  xml_str += generate_indent()  + '<order sym="AMZN" amount="200" limit="127"/>\n'  #status id=2
  xml_str += generate_indent()  + '<order sym="AMZN" amount="400" limit="125"/>\n'  #status id=3
  xml_str += '</transactions>\n'

  return  str(len(xml_str)) + "\n" + xml_str

def test_transaction_matching2():
  """
  230
  <?xml version="1.0" encoding="UTF-8"?>
  <transactions id="2">
    <order sym="AMZN" amount="-100" limit="130"/>
    <order sym="AMZN" amount="-500" limit="128"/>
    <order sym="AMZN" amount="-200" limit="140"/>
  </transactions>
  """
  xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n'
  xml_str += '<transactions id="2">\n'
  xml_str += generate_indent()  + '<order sym="AMZN" amount="-100" limit="130"/>\n'  #status id=4
  xml_str += generate_indent()  + '<order sym="AMZN" amount="-500" limit="128"/>\n'  #status id=5
  xml_str += generate_indent()  + '<order sym="AMZN" amount="-200" limit="140"/>\n'  #status id=6
  xml_str += '</transactions>\n'

  return str(len(xml_str)) + "\n" + xml_str

def test_transaction_matching3():
  """
  137
  <?xml version="1.0" encoding="UTF-8"?>
  <transactions id="2">
    <order sym="AMZN" amount="-400" limit="124"/>
  </transactions>
  """
  xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n'
  xml_str += '<transactions id="2">\n'
  xml_str += generate_indent()  + '<order sym="AMZN" amount="-400" limit="124"/>\n'  #status id=7
  xml_str += '</transactions>\n'

  return str(len(xml_str)) + "\n" + xml_str

def test_transaction_result():
  """
  94
  <?xml version="1.0" encoding="UTF-8"?>
  <transactions id="2">
    <query id="7">
  </transactions>
  """
  xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n'
  xml_str += '<transactions id="2">\n'
  xml_str += generate_indent()  + '<query id="7"/>\n'  #Or the corresponding status ID here.
  xml_str += '</transactions>\n'

  return str(len(xml_str)) + "\n" + xml_str

def show_sell_state():
  xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n'
  xml_str += '<transactions id="2">\n'
  xml_str += generate_indent()  + '<query id="5"/>\n'
  xml_str += generate_indent()  + '<query id="6"/>\n'
  xml_str += generate_indent()  + '<query id="7"/>\n'
  xml_str += '</transactions>\n'

  return str(len(xml_str)) + "\n" + xml_str

def show_buy_state():
  xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n'
  xml_str += '<transactions id="1">\n'
  xml_str += generate_indent()  + '<query id="2"/>\n'
  xml_str += generate_indent()  + '<query id="3"/>\n'
  xml_str += generate_indent()  + '<query id="4"/>\n'
  xml_str += '</transactions>\n'

  return str(len(xml_str)) + "\n" + xml_str


def test_transaction_matching_all(client_socket):
  send_xml_to_server(setup_test_transcation_matching(), client_socket)
  send_xml_to_server(test_transaction_matching1(), client_socket)
  send_xml_to_server(test_transaction_matching2(), client_socket)
  send_xml_to_server(test_transaction_matching3(), client_socket)
  send_xml_to_server(test_transaction_result(), client_socket)
  send_xml_to_server(show_buy_state(), client_socket)
  send_xml_to_server(show_sell_state(), client_socket)

def test_all_transaction_operations_setup():
  xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n'
  xml_str += '<create>\n'
  xml_str += generate_indent()  + '<account id="3" balance="200000"/>\n'
  xml_str += generate_indent()  + '<account id="4" balance="100000"/>\n'
  xml_str += generate_indent()  + '<symbol sym="GOOG">\n'
  xml_str += generate_indent(2) + '<account id="4">100000</account>\n'
  xml_str += generate_indent()  + '</symbol>\n'
  xml_str += '</create>\n'

  return  str(len(xml_str)) + "\n" + xml_str

def test_all_transaction_operation_order_buy():
  xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n'
  xml_str += '<transactions id="3">\n'
  xml_str += generate_indent()  + '<order sym="GOOG" amount="100" limit="123"/>\n'
  xml_str += generate_indent()  + '<order sym="GOOG" amount="100" limit="0"/>\n'
  xml_str += '</transactions>\n'

  return str(len(xml_str)) + "\n" + xml_str

def test_all_transaction_operation_order_sell():
  xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n'
  xml_str += '<transactions id="4">\n'
  xml_str += generate_indent()  + '<order sym="GOOG" amount="-50" limit="123"/>\n'
  xml_str += '</transactions>\n'

  return str(len(xml_str)) + "\n" + xml_str

def test_all_transaction_operation_cancel(account_id, transaction_id):
  #write cancel here to cancel a specific transaction ID
  xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n'
  xml_str += f'<transactions id="{account_id}">\n'
  xml_str += generate_indent()  + f'<cancel id="{transaction_id}"/>\n'
  xml_str += '</transactions>\n'
  return str(len(xml_str)) + "\n" + xml_str

def test_all_transaction_operation_query(account_id, transaction_id):
  #write query here to see the result of a specific transaction ID.
  xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n'
  xml_str += f'<transactions id="{account_id}">\n'
  xml_str += generate_indent()  + f'<query id="{transaction_id}"/>\n'
  xml_str += '</transactions>\n'
  return str(len(xml_str)) + "\n" + xml_str

def test_all_transaction_operations(client_socket):
  # Setup
  send_xml_to_server(test_all_transaction_operations_setup(), client_socket)

  # Send buy orders and get their IDs
  buy_response_xml = send_xml_to_server(test_all_transaction_operation_order_buy(), client_socket)
  buy_ids = []
  try:
    root = ET.fromstring(buy_response_xml)
    for opened in root.findall('opened'):
      buy_ids.append(opened.get('id'))
  except ET.ParseError as e:
    print(f"Error parsing buy response: {e}")
    print(f"Response was: {buy_response_xml}")
    return # Cannot proceed without IDs

  if len(buy_ids) < 2:
      print(f"Error: Expected at least 2 opened orders for buy, got {len(buy_ids)}")
      print(f"Buy IDs received: {buy_ids}")
      # Decide how to handle this - maybe still try to send sell/cancel/query if possible?
      # For now, let's return if we don't have enough IDs for the planned test.
      return

  # Send sell orders (we don't necessarily need their IDs for this specific test flow)
  send_xml_to_server(test_all_transaction_operation_order_sell(), client_socket)

  # Cancel the second buy order (assuming IDs are sequential as received)
  if len(buy_ids) >= 2:
      cancel_id = buy_ids[1] # ID of the <order sym="GOOG" amount="100" limit="0">
      account_id_cancel = "3" # Account that made the buy order
      send_xml_to_server(test_all_transaction_operation_cancel(account_id_cancel, cancel_id), client_socket)
  else:
      print("Skipping cancel test: Not enough buy order IDs received.")


  # Query the first buy order
  if len(buy_ids) >= 1:
      query_id = buy_ids[0] # ID of the <order sym="GOOG" amount="100" limit="123">
      account_id_query = "3" # Account that made the buy order
      send_xml_to_server(test_all_transaction_operation_query(account_id_query, query_id), client_socket)
  else:
      print("Skipping query test: No buy order IDs received.")


def send_xml_to_server(xml_request, client_socket):
  """
  Sends the XML string to the Server listening on PORT 12345
  Returns the server's response string.
  """
  print("--------------------------------------------------")
  client_socket.sendall(xml_request.encode('utf-8'))
  print(f"Sent request:\n{xml_request}")
  response_bytes = client_socket.recv(4096)
  response_str = response_bytes.decode('utf-8')
  print(f"Server response:\n{response_str}")
  print("--------------------------------------------------\n")
  return response_str # Return the response

def basic_order_transaction_test():
  """
  133
  <?xml version="1.0" encoding="UTF-8"?>
  <transactions id="123456">
    <order sym="SPY" amount="10" limit="100"/>
  </transactions>
  """
  xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n'
  xml_str += '<transactions id="123456">\n'
  xml_str += generate_indent() + '<order sym="SPY" amount="10" limit="100"/>\n'
  xml_str += '</transactions>\n'

  return str(len(xml_str)) + "\n" + xml_str

def test_transaction_error_account_DNE():
  """
  135
  <?xml version="1.0" encoding="UTF-8"?>
  <transactions id="999999">
    <order sym="SPY" amount="10" limit="100"/>
  </transactions>
  """
  xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n'
  xml_str += '<transactions id="999999">\n'
  xml_str += generate_indent() + '<order sym="SPY" amount="10" limit="100"/>\n'
  xml_str += '</transactions>\n'

  return str(len(xml_str)) + "\n" + xml_str


def main():
    #Server address
    #hostname = socket.gethostname()
    hostname = "vcm-46756.vm.duke.edu"
    server_address = (hostname, 12345)

    # Create the socket
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    try:
        client_socket.connect(server_address)
        print(f"Connected to server at {server_address}")

        #Send XML to create an accoutn and a symbol. Should return an created tag for both.
        #Expected : <results><created id="123456"/><created sym="SPY" id="123456"/></results>
        send_xml_to_server(basic_creation_test(), client_socket)

        #Send XML to create an accoutn and a symbol. Should return an created tag for both.
        #Expected : <results><created id="123456"/><created sym="SPY" id="123456"/></results>
        # This tests creating an existing account/symbol - should produce errors
        send_xml_to_server(basic_creation_test(), client_socket) # Expect errors here

        #Send XML to test empty create
        # should respond with results
        send_xml_to_server(test_empty_create(), client_socket)

        #Send XML to make an symbol with an account that does not exist
        # should respond with results and an error saying account does not exist
        send_xml_to_server(test_create_symbol_error_account_DNE(), client_socket)

        #Send XML to make an order transaction.
        # should respond with results and an status
        send_xml_to_server(basic_order_transaction_test(), client_socket)

        #Send XML to make an invalid transaction.
        # should respond error account does not exist
        send_xml_to_server(test_transaction_error_account_DNE(), client_socket)

        # Sends a series of XML to test order matching mechanism
        test_transaction_matching_all(client_socket)

        # Sends a series of XML to test query and cancel
        test_all_transaction_operations(client_socket) # Now runs the refactored test

    except ConnectionRefusedError:
        print(f"Error: Connection refused. Is the server running at {server_address}?")
    except socket.timeout:
        print("Error: Socket connection timed out.")
    except ET.ParseError as e:
        print(f"XML Parsing Error during testing: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")


    finally:
        # Close the connection
        print("Closing client socket.")
        client_socket.close()

if __name__ == "__main__":
    main()
