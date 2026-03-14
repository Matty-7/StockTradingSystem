# High-Performance Exchange Matching Server
**Jingheng Huan** · Duke University, ECE 568

---

## Abstract

I implement a concurrent financial exchange matching engine in Python, supporting buy, sell, query, and cancel over a TCP/XML protocol. Eight targeted optimizations — spanning I/O, in-memory data structures, and concurrency control — bring throughput from **156 to 728 req/s** across 1–8 cores (**4.7× scaling**) with end-to-end latency stable at **~11 ms**. Zero system errors across 6,000 concurrent operations confirm correctness under load.

---

## Objectives

- Implement price-time priority matching with full order lifecycle support
- Achieve near-linear throughput scaling from 1 to 8 CPU cores
- Maintain stable per-request latency under high concurrency
- Quantify and eliminate each performance bottleneck systematically

---

## Methods

### Architecture

**Pre-fork multi-process server**: parent binds TCP socket, forks N workers that each `accept()` independently. Eliminates Python's GIL — each worker is a separate OS process.

Each worker holds an **in-memory order book** (`SortedList`, O(log N)). Matching uses a hybrid path: in-memory fast lookup → `SELECT FOR UPDATE SKIP LOCKED` confirmation → DB fallback scan.

```
Clients → [Worker-1 | Worker-2 | … | Worker-N]
                         ↓
                    PostgreSQL
```

### Key Optimizations

| # | What | Effect |
|---|---|---|
| 1 | `synchronous_commit = off` | Removes per-COMMIT fsync (~1–3 ms/tx) |
| 2 | Upsert position update | 2 round-trips → 1 |
| 3 | In-memory order book | −17–29% match latency |
| 4 | `LISTEN/NOTIFY` cross-worker sync | −14–33% latency, −72–83% variance |
| 5 | Adaptive connection pool | −25% 1-core E2E latency |
| 6 | Buffered `recv` + `TCP_NODELAY` | N syscalls → 1; no Nagle delay |

### Benchmark Setup

- **50 accounts**, 500 req/iter, 10 concurrent threads, n = 10 iterations
- **Throughput**: persistent connections, mixed buy/sell/query/cancel
- **E2E latency**: new TCP connection per request (measures full RTT)
- **Match-only latency**: `perf_counter()` around `match_orders()` server-side

---

## Results

### Throughput vs Cores

| Cores | req/s | ±SD | Scale |
|---|---|---|---|
| 1 | 155.95 | ±5.83 | 1.0× |
| 2 | 305.66 | ±12.88 | **2.0×** |
| 4 | 516.24 | ±39.60 | **3.3×** |
| 8 | **727.86** | ±38.62 | **4.7×** |

### Latency vs Cores

| Cores | E2E (ms) | Match-Only (ms) | Gap |
|---|---|---|---|
| 1 | 10.44 | 6.26 | 4.18 ms |
| 2 | 10.78 | 6.48 | 4.30 ms |
| 4 | 10.82 | 6.57 | 4.25 ms |
| 8 | **11.21** | **6.84** | 4.37 ms |

E2E rises only **+0.77 ms** (1→8 cores). The constant **~4.2 ms gap** (TCP + XML parse + account lock) confirms per-request overhead is independent of worker count.

### Concurrency Correctness (100 threads, 6,000 ops)

- Success: **5,572 / 6,000 (92.87%)**
- Business rejections (expected): 428
- **System errors: 0**

---

## Conclusion

Systematic, measurement-driven optimization extracts **4.7× throughput** from a Python exchange under real PostgreSQL constraints — without architectural overhaul.

The system is now **database-lock bound**, not CPU-bound. Remaining ~6.8 ms match latency breaks down as:

- **~4.2 ms** — fixed overhead (TCP + parse + account lock + commit)
- **~2.6 ms** — 6 Python↔PostgreSQL round-trips inside `match_orders()`

**Future Work:**
- **Single-CTE atomic match** — collapse 6 DB round-trips to 1 (−40–50% match latency), limited by inability to express partial-fill loops in pure SQL
- **Symbol-Partitioned Routing** — hash orders by symbol to dedicated workers; lock-free in-memory matching + async persistence; target **< 1 ms** (cf. LMAX Disruptor)

---

## References

1. PostgreSQL Docs — *LISTEN/NOTIFY*, *synchronous_commit* (postgresql.org)
2. Grant Jenks — *sortedcontainers* (grantjenks.com)
3. Gunther, N. J. (2007). *Guerrilla Capacity Planning*. Springer. *(USL)*
4. Thompson et al. (2011). *LMAX Disruptor*. lmax-exchange.github.io
5. Stevens et al. (2003). *UNIX Network Programming*, 3rd ed. *(TCP_NODELAY §7.9)*
