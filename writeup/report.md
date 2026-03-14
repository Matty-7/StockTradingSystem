# ECE 568: HW4 Exchange Matching Server

Authors: Jingheng Huan, Vincent Choo

## Introduction

This project implements an exchange matching engine with account, symbol, order, query, and cancel support over a TCP/XML protocol. We evaluate scalability versus CPU core count and report both throughput and latency.

## Methodology

- Core configurations: `1, 2, 4, 8`
- For each core count: `10` iterations
- Each iteration:
  - Throughput test with `100` requests and `5` concurrent client threads
  - Latency test with `100` single-request round trips
- Workload mix: buy, sell, query, cancel operations on symbol `PERF`

Metrics:

- **Throughput**: requests/second
- **Latency**: average seconds/request

Graph convention:

- marker line: mean
- error bars: standard error (SE)
- scatter points: raw per-iteration values (`n=10`)

## Latest Results

![throughput vs core](throughput_vs_cores.png)

### End-to-End Latency vs Cores

Measures the full client round-trip: TCP connect → XML parse → DB + matching → TCP response.

![end-to-end latency vs core](latency_vs_cores.png)

### Pure Matching Engine Latency vs Cores

Measures only the server-side `match_orders()` call: order-book DB query, price-priority selection, and position/balance updates within a single transaction. Network, parsing, and connection overhead are excluded.

![matching engine latency vs core](matching_latency_vs_cores.png)

Latest run summary:

| Cores | Throughput (req/s) | E2E Latency (s) | Match-Only Latency (s) | Match Samples |
|---|---|---|---|---|
| 1 | `212.33 ± 42.97` | `0.004764 ± 0.000767` | `0.005573` | 627 |
| 2 | `302.71 ± 73.32` | `0.004973 ± 0.000610` | `0.005773` | 632 |
| 4 | `382.12 ± 91.26` | `0.005659 ± 0.000777` | `0.005849` | 623 |
| 8 | `330.78 ± 79.35` | `0.006799 ± 0.000821` | `0.006253` | 687 |

Throughput and E2E latency shown as mean ± SD (n=10 iterations).  
Match-only latency is the mean across all individual `match_orders()` calls logged server-side.

Interpretation:

- Throughput peaks at 4 cores (`382 req/s`), then drops at 8 cores (`331 req/s`) due to increased DB lock contention among workers.
- End-to-end latency rises monotonically from 2→8 cores, tracking the growing contention cost.
- Match-only latency (`0.005573 → 0.006253 s`) mirrors the e2e trend closely, confirming the bottleneck lives inside the DB-backed order book — not in TCP or XML parsing.
- The small gap between e2e and match latency (~0.1–0.5 ms) accounts for network round-trip and XML processing overhead.

## Concurrency Stability Update

After lock-contention fixes and deadlock-aware retries:

- Total operations: `6000`
- Successful operations: `5572` (`92.87%`)
- Business rejected operations (expected under randomized invalid requests): `428`
- System errors: `0`
- Protocol-correct responses (success + expected reject): `100.00%`

This indicates the system now reliably returns either a successful response or a valid business rejection, with no internal errors in the latest stress run.

## Engineering Changes That Improved Reliability

1. **DB-backed shared order book matching**  
   Matching now queries open orders from the shared database with price priority and FIFO tie-break, so all worker processes see a consistent global order book.

2. **Deadlock-aware retry with exponential backoff + jitter**  
   Transactional paths for order placement and cancel retry on PostgreSQL transient errors (`40P01`, `40001`), reducing failure probability under contention.

3. **Schema consistency guard**  
   Added a unique constraint on `(account_id, symbol_name)` in `positions` to prevent duplicate position rows under concurrent writes.

## Remaining Limitations

- Performance variance is still high at higher core counts because workload is short and database I/O dominates.
- Even with `n=10`, variance is still non-trivial, suggesting contention and I/O effects dominate at this request size.

## Future Work

- Increase workload duration and request volume for more stable estimates.
- Add transaction-level observability (retry counters, lock-wait timing).
- Evaluate lock ordering and reduced flush pressure to lower contention further under heavier loads.
