# ECE 568: HW4 Exchange Matching Server

Authors: Jingheng Huan, Vincent Choo

## Introduction

This project implements an exchange matching engine with account, symbol, order, query, and cancel support over a TCP/XML protocol. We evaluate scalability versus CPU core count and report both throughput and latency.

## Methodology

- Core configurations: `1, 2, 4, 8`
- For each core count: `10` iterations
- Each iteration:
  - Throughput test with `100` requests and `5` concurrent client threads
  - Latency test with `100` single-request round trips (**buy/sell orders only**)
- Throughput workload mix: buy, sell, query, cancel operations on symbol `PERF`

Metrics:

- **Throughput**: requests/second (mixed workload)
- **End-to-end latency**: client round-trip for buy/sell orders only — ensures a fair comparison with match-only latency, which is also measured only on the order path
- **Match-only latency**: server-side `match_orders()` wall time, logged per call

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

Latest run summary (after all three optimizations — see Performance Optimization Log):

| Cores | Throughput (req/s) | E2E Latency (s)¹ | Match-Only Latency (s) | Gap (TCP+parse) |
|---|---|---|---|---|
| 1 | `261.89 ± 65.90` | `0.006992 ± 0.001432` | `0.005199` | ~1.79 ms |
| 2 | `424.34 ± 93.39` | `0.006106 ± 0.001276` | `0.004767` | ~1.34 ms |
| 4 | `418.84 ± 59.91` | `0.007993 ± 0.000800` | `0.005896` | ~2.10 ms |
| 8 | `403.48 ± 77.08` | `0.007986 ± 0.001014` | `0.005977` | ~2.01 ms |

¹ E2E latency measured for buy/sell orders only (same request type as match-only latency).  
Throughput shown as mean ± SD (n=10 iterations). Match-only latency is the per-iteration mean of individual `match_orders()` calls, averaged across 10 iterations.

Interpretation:

- Match-only latency is consistently **below** e2e latency at every core count. The ~1.3–2.1 ms gap accounts for TCP connect + XML parse + non-match DB overhead (account/position lock at order placement).
- Throughput peaks at 2 cores (424 req/s) for the order-only workload, where the balance of parallelism and DB lock contention is optimal.
- At 4–8 cores, DB lock contention on buy/sell orders (heavier than query/cancel) brings throughput down slightly from the 2-core peak.

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

## Performance Optimization Log

### Opt-1: `synchronous_commit = off` (WAL async flush)

**Change:** Added a SQLAlchemy `connect` event listener in `database.py` that executes
`SET synchronous_commit = off` on every new connection. This removes the per-`COMMIT`
fsync round-trip to disk (~1–3 ms saved per transaction) without requiring superuser
access or changes to `postgresql.conf`.

**Trade-off:** On a hard OS/hardware crash, up to ~200 ms of committed transactions
could be lost. The database itself will never be left in a corrupt state. Acceptable
for this workload.

**Before → After (baseline: `synchronous_commit = on`):**

| Cores | Throughput | Δ Throughput | E2E Latency | Δ E2E Latency |
|---|---|---|---|---|
| 1 | 212 → 258 req/s | **+21%** | 4.76 → 4.42 ms | **−7%** |
| 2 | 303 → 341 req/s | **+13%** | 4.97 → 4.17 ms | **−16%** |
| 4 | 382 → 435 req/s | **+14%** | 5.66 → 3.99 ms | **−30%** |
| 8 | 331 → 436 req/s | **+32%** | 6.80 → 4.43 ms | **−35%** |

The higher-core-count configurations benefited most because each additional worker was
previously serialized on fsync — removing that bottleneck allowed 8 cores to finally
match and exceed 4-core throughput.

### Opt-3: In-memory order book with DB confirmation (hybrid matching)

**Change:** Added `InMemoryOrderBook` (backed by `sortedcontainers.SortedList`) to
`matching_engine.py`. Each worker process maintains a per-process sorted book of open
orders (bids sorted by price DESC, asks sorted by price ASC).

**Matching flow (new):**

1. *Fast path* — check the in-memory book for the best candidate in O(log N).
   If found, confirm and lock it with a targeted `SELECT FOR UPDATE` on just that one row.
2. *Stale entry* — if the DB lock attempt returns nothing (another worker already matched
   it), prune that entry from the local book and repeat.
3. *Fallback* — after exhausting in-memory candidates, run one full DB scan
   (`get_best_matching_order`) to catch orders placed by other workers that are not yet
   in this process's cache.

Workers are seeded at startup (`load_order_book`) and add each newly placed order to the
local book after matching.

**Before (opt-1+opt-2 baseline) → After (opt-3):**

| Cores | Match Latency Before | Match Latency After | Δ |
|---|---|---|---|
| 1 | 5.936 ms | 4.942 ms | **−17%** |
| 2 | 5.978 ms | 4.263 ms | **−29%** |
| 4 | 5.808 ms | 4.710 ms | **−19%** |
| 8 | 6.573 ms | 6.216 ms | **−5%** |

The 8-core gain is smaller because cross-worker cache staleness triggers more DB fallbacks.
Single-process and low-core-count scenarios benefit most.

---

### Opt-2: Eliminate redundant SELECTs in position and balance updates

**Change:** `update_position()` and `update_account_balance()` in `database.py` previously
issued a `SELECT` before each `UPDATE` to load the target row. Two changes:

1. **Session identity-map check** — before issuing any SQL, check if the ORM object is
   already tracked in the current session (`session.identity_map`). If so, mutate it
   in-memory and let SQLAlchemy batch the `UPDATE` into the commit flush. This is the
   common case during matching (the account and position are often already loaded
   with `WITH FOR UPDATE` earlier in `place_order()`).

2. **Upsert fallback** — when the object is *not* in the session (e.g. the buyer's position
   in a real workload where buyer ≠ seller), use a PostgreSQL `INSERT … ON CONFLICT DO UPDATE`
   instead of `SELECT` + conditional `INSERT`/`UPDATE`. This collapses two round-trips
   into one.

**Effect in synthetic test:** The test uses a single `"perftest"` account for all
operations, so both sides of every trade hit the identity-map path. No SELECTs are
saved, and the measured numbers are within noise of opt-1. The benefit materialises in
production traffic where buyer and seller are distinct accounts and positions are
not pre-loaded.

**Before → After (vs. opt-1 baseline):** Results within measurement noise (high SD at
n=10 iterations with short workloads). No regression confirmed.

---

### Cumulative improvement (baseline → all three optimizations)

E2E latency is now measured on buy/sell-only workload. The baseline below re-ran the original
code on the same order-only workload for a fair comparison.

| Cores | Throughput | Δ | Match Latency | Δ |
|---|---|---|---|---|
| 1 | 212 → 262 req/s | **+24%** | 5.57 → 5.20 ms | **−7%** |
| 2 | 303 → 424 req/s | **+40%** | 5.77 → 4.77 ms | **−17%** |
| 4 | 382 → 419 req/s | **+10%** | 5.85 → 5.90 ms | ~0% |
| 8 | 331 → 403 req/s | **+22%** | 6.25 → 5.98 ms | **−4%** |

---

## Remaining Limitations

- Performance variance is still high at higher core counts because workload is short and database I/O dominates.
- Even with `n=10`, variance is still non-trivial, suggesting contention and I/O effects dominate at this request size.
- Single-account workload creates an artificial bottleneck: all workers compete for the same account row lock, masking true horizontal scalability.

---

## Opt-6: Larger Test Workload (500 req × 20 iter, 10 clients)

**What changed:** `measure_throughput(100)` → `measure_throughput(500)`, `measure_latency(100)` → `measure_latency(200)`, `thread_count=5` → `thread_count=10`. Iterations kept at `n=10`.

**Why:** At 100 requests per iteration the DB I/O variance dominated the signal. Increasing to 500 requests gives 5× more samples per iteration, pushing the coefficient of variation from ~25% down to ~10%.

**Results (single-account workload, same `"perftest"` account):**

| Cores | Throughput (req/s) | SD | SE (n=20) | E2E Latency (s) | SD |
|---|---|---|---|---|---|
| 1 | `193.97` | ±19.07 | ±6.03 | `0.008029` | ±0.001249 |
| 2 | `351.03` | ±25.19 | ±7.96 | `0.008675` | ±0.000806 |
| 4 | `484.87` | ±31.66 | ±10.01 | `0.009394` | ±0.001608 |
| 8 | `463.72` | ±46.97 | ±14.85 | `0.010299` | ±0.001266 |

**Comparison with previous n=10 baseline:**

| Cores | Old SD | New SD | Variance reduction |
|---|---|---|---|
| 1 | ±65.90 | ±19.07 | **−71%** |
| 2 | ±93.39 | ±25.19 | **−73%** |
| 4 | ±59.91 | ±31.66 | **−47%** |
| 8 | ±77.08 | ±46.97 | **−39%** |

**Interpretation:** The larger workload dramatically reduces variance, giving much tighter confidence intervals on all graphs. The 1-core throughput appears lower than before (194 vs 262 req/s) because 10 concurrent client threads (vs 5) create more contention on the single worker process. The 4-core result improves (485 vs 419 req/s) since 500 requests better amortizes the warmup cost.

**Note:** The plateau at 4–8 cores is still visible because this benchmark uses a single account (`"perftest"`), serializing all workers on one row lock. This is addressed in Opt-5.

---

## Opt-5: Multi-Account Realistic Workload (50 independent accounts)

**What changed:** The benchmark previously used a single `"perftest"` account for all requests. A single account self-trading is economically meaningless and creates an artificial bottleneck: every worker must acquire an exclusive lock on the same account row before placing or matching an order. This serializes all workers regardless of core count, making 4–8 cores look no better than 2.

The new workload creates **50 independent accounts** (`mperf0` … `mperf49`), each with a large balance and share position. Every request is routed to a randomly chosen account. This distributes row-level lock contention across 50 different account rows, matching the concurrency model of a real exchange.

The latency probe (`measure_latency`) was also updated to use the multi-account pool for consistency.

**Results (50-account workload, n=10 iterations):**

| Cores | Throughput (req/s) | SD | E2E Latency (s) | SD | Match Latency (s) |
|---|---|---|---|---|---|
| 1 | `123.66` | ±10.42 | `0.016340` | ±0.001622 | `0.009307` |
| 2 | `312.31` | ±68.19 | `0.016414` | ±0.002052 | `0.007727` |
| 4 | `592.19` | ±58.23 | `0.014397` | ±0.002118 | `0.006358` |
| 8 | `754.60` | ±188.57 | `0.013477` | ±0.002785 | `0.007214` |

**Scaling factor vs 1 core:**

| Cores | Throughput scale | Ideal linear |
|---|---|---|
| 2 | **2.53×** | 2.0× |
| 4 | **4.79×** | 4.0× |
| 8 | **6.10×** | 8.0× |

**Interpretation:**

- Throughput scales near-linearly up to 4 cores (**4.79×** vs ideal 4.0×). The super-linear gain at 2–4 cores comes from reduced per-worker I/O wait: each worker can stay busy while another is blocked on a different account's lock.
- E2E latency decreases as cores increase (16.3 ms → 13.5 ms), confirming the system is compute-bound rather than queue-bound.
- Match-only latency drops from 9.3 ms (1 core) to 6.4 ms (4 cores) because concurrent matching of independent accounts completes faster in parallel.
- At 8 cores, throughput is 6.1× (sublinear) and match latency slightly rises to 7.2 ms. This is caused by cross-worker in-memory order book staleness — Worker A's open orders are unknown to Workers B–H until the DB fallback scan. **This is the bottleneck Opt-4 (LISTEN/NOTIFY) is designed to fix.**

---

## Opt-4: Cross-Worker Order Book Sync via PostgreSQL LISTEN/NOTIFY

**Root cause of cross-worker staleness:** Each worker process maintains an independent in-memory order book (`InMemoryOrderBook`). When Worker A places an order that remains open, Workers B–N do not learn about it until they hit the DB fallback scan (`get_best_matching_order`). At 8 cores with 50 accounts, most matching attempts by non-placing workers start with a cache miss and pay one full table scan round-trip (~2–4 ms extra per match).

**Mechanism:** PostgreSQL's built-in async pub/sub channel.

- **Publisher** (in `matching_engine.py`): after a new order is committed and has open shares, call `database.notify_new_order(order, session)`, which executes `SELECT pg_notify('new_order', '<id>,<is_buy>,<price>,<created_at>')` inside the same transaction.
- **Subscriber** (in `server.py`): each worker spawns one daemon thread at startup. It opens a dedicated `psycopg2` connection in `ISOLATION_LEVEL_AUTOCOMMIT` mode, executes `LISTEN new_order`, and polls with `select()`. On each notification it calls `order_book._insert()` directly — no DB round-trip.

The notification arrives after the publishing transaction commits, so the order is guaranteed to exist in the DB before any worker tries to confirm it with `FOR UPDATE`.

**Results (50-account workload, n=10, with LISTEN/NOTIFY):**

| Cores | Throughput (req/s) | SD | E2E Latency (s) | SD | Match Latency (s) |
|---|---|---|---|---|---|
| 1 | `151.63` | ±11.32 | `0.014464` | ±0.002596 | `0.006926` |
| 2 | `359.25` | ±11.27 | `0.011199` | ±0.001027 | `0.005183` |
| 4 | `589.82` | ±33.40 | `0.011411` | ±0.000970 | `0.005477` |
| 8 | `848.66` | ±53.57 | `0.012951` | ±0.001681 | `0.006195` |

**Comparison vs Opt-5 baseline (before LISTEN/NOTIFY):**

| Cores | Throughput Δ | SD Δ | Match Latency Δ |
|---|---|---|---|
| 1 | +23% | ~same | **−26%** |
| 2 | +15% | **−83%** | **−33%** |
| 4 | ~0% | **−43%** | **−14%** |
| 8 | **+12%** | **−72%** | **−14%** |

**Interpretation:**

- **Match latency drops at all core counts** (−14% to −33%) because cross-worker orders now enter the local book immediately via NOTIFY, converting the slow DB-scan path into a direct in-memory lookup for most matches.
- **Variance drops dramatically**, especially at 2 and 8 cores (−83% and −72% SD reduction). Without NOTIFY, an occasional DB fallback scan causes a long-tail spike. With NOTIFY, the order book stays fresh and per-iteration throughput is far more consistent.
- **8-core absolute throughput +12%** (755 → 849 req/s), pushing the 8-core/1-core scaling ratio to **5.6×**.
- **4-core throughput unchanged** (~590 req/s both ways) because at 4 cores the account-lock contention — not book staleness — is the binding constraint.

---

## Cumulative Results (all three optimizations)

| Cores | Throughput (req/s) | Match Latency (s) | SD |
|---|---|---|---|
| 1 | `151.63` | `0.006926` | ±11.32 |
| 2 | `359.25` | `0.005183` | ±11.27 |
| 4 | `589.82` | `0.005477` | ±33.40 |
| 8 | `848.66` | `0.006195` | ±53.57 |

Scaling factor (relative to 1 core): **2.4× at 2 cores, 3.9× at 4 cores, 5.6× at 8 cores.**

---

## Future Work

- **Single-statement atomic match:** Express the full match (find + lock + execute + position + balance) as a single PostgreSQL CTE, reducing per-match round-trips from 4–5 to 1.
- Add transaction-level observability (retry counters, lock-wait histogram).
