# Exchange Matching Engine

## Authors
- Jingheng Huan
- Vincent Choo

## Overview
This project implements a TCP/XML exchange server for ECE 568 HW4. It supports account and symbol creation, order placement, matching, query, and cancel, with matching behavior following price priority and FIFO tie-break rules.

## Key Features
- Pre-fork multi-process server on port `12345`
- Shared database-backed order book for cross-process consistency
- Atomic order execution and balance/position updates
- Deadlock-aware retry for transactional order and cancel paths
- Functional, edge-case, concurrency, and performance test suites

## Quick Start

### 1) Start services
```bash
docker-compose down && docker-compose up --build
```

### 2) Run the full test suite
```bash
python3 testing/run_all_tests.py --skip-server
```

### 3) Run only performance tests (regenerates charts)
```bash
python3 testing/performance_test.py
```

## Project Layout
- `server.py`: pre-fork TCP server and worker lifecycle
- `xml_handler.py`: request parsing and response serialization
- `matching_engine.py`: order validation, matching, execution logic
- `database.py` and `model.py`: persistence layer and schema
- `testing/`: functional and scalability tests
- `writeup/`: report and generated performance figures

## Communication Protocol
The server accepts requests as:
1) one line with XML payload length, then
2) raw XML payload with root `<create>` or `<transactions>`.

Responses always use root `<results>`.

## Performance Notes
Performance and scalability figures are generated from `testing/performance_test.py` and written to:
- `writeup/throughput_vs_cores.png`
- `writeup/latency_vs_cores.png`
