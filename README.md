# Exchange Matching Engine

## Authors
- Jingheng Huan
- Vincent Choo

## Overview
This project implements a stock/commodity exchange matching engine: a server that matches buy and sell orders for a market. The system maintains accounts, positions, and handles order execution following standard market rules.

## Key Features
- Account management with balance tracking
- Symbol creation and position tracking
- Order placement (buy/sell) with limit prices
- Order matching using price-time priority
- Order cancellation and status querying
- Atomic transaction execution

## Running the Application

### Prerequisites
- Docker and docker-compose installed
- Python 3
- sqlalchemy
- psycopg2-binary
- matplotlib

### Start the Server
In your first terminal, run:
```bash
docker-compose down && docker-compose up --build
```
This will start the PostgreSQL database and the exchange server.

### Run the Tests
In a second terminal, run:
```bash
python3 testing/run_all_tests.py --skip-server
```
The `--skip-server` flag indicates that the tests should use the already running server instance from the first terminal.

## System Design

### Core Concepts
- **Symbol**: An identifier for a stock or commodity (e.g., SPY, BTC)
- **Position**: Amount of a particular symbol owned by an account
- **Account**: Contains a balance (USD) and positions in different symbols
- **Order**: A request to buy or sell with a symbol, amount, and limit price
- **Order Matching**: Orders match when they are for the same symbol and have compatible prices
- **Order Execution**: When matched orders result in the exchange of shares and money

### Communication Protocol
The server uses an XML-based protocol over TCP connections on port 12345:
- Create accounts and symbols
- Place buy/sell orders
- Query order status
- Cancel open orders

### Order Matching Rules
- Orders are matched at the best possible price
- When multiple orders have the same price, earlier orders have priority
- Orders can be partially executed if no single matching order is available

## Performance and Scalability
The system is designed to scale across multiple CPU cores. Performance test results are available in the `writeup` directory. 
