# ECE 568: HW4 Exchange Matching Server
Authors: Jingheng Huan, Vincent Choo

## Introduction
For this project, we created a stock exchange matching server using python. In our report, we will explore the scalability of our code by exploring how throughput and latency of our server changes as we increase the number of CPU cores. For our experiment, we used 1, 2, 4, and 8 cores since our vcm has 8 cores.

## Testing Methodology
To test our performance, we used the Linux command `taskset -c` to specify which cores to use to limit the number of cores running the processes when executing tests for different core counts. For our performance test, we generated 100 random transaction requests with the following characteristics:
- A mix of operation types: buy, sell, query, and cancel operations 
- Buy orders with amounts ranging from 1 to 100 shares and prices between $10 and $100
- Sell orders with smaller amounts (1 to 10 shares) to avoid depleting positions
- All operations targeting a single stock symbol "PERF"
- 5 concurrent client threads sending requests simultaneously

These requests were sent to the server, and we measured the following metrics:
- **Throughput**: Number of requests processed per second (req/sec)
- **Latency**: Average response time in seconds per transaction

Each test was run 3 times for each core configuration (1, 2, 4, and 8 cores), and we calculated the average and standard error from these results.

Our matching engine implementation correctly follows the exchange matching rules specified in the assignment, particularly ensuring that orders execute at the price of the order that was open first. This is implemented in our code by comparing the `created_at` timestamps of the matching orders and using the limit price of the older order as the execution price.

## Test Results
For our tests, we had the following results:

![throughput vs core](throughput_vs_cores.png)

![latency vs core](latency_vs_cores.png)

The throughput results show that increasing the number of cores from 1 to 8 did not lead to significant performance improvements. The average throughput remained relatively constant across all core configurations, with slight variations falling within the standard error range. 

Similarly, the latency measurements show no substantial decrease as we added more cores. In fact, there appears to be a slight increase in latency variance with more cores, though this is not statistically significant given the overlapping error bars.

## Analysis
From our experimental results, there was no significant performance improvement when increasing the number of cores used in the server. (No t-test was performed; this conclusion is based on the large standard error.) This suggests that our server does not scale well. Upon closer examination of our server code, we identified the following factors contributing to this limitation:

1. **Contention on Shared Resources**
  Our matching server uses lock to ensure that only one thread handles one resource at a time. Specifically, in our `matching_engine.py`, we implement a global lock (`self.lock`) for the order matching process. This means that regardless of how many cores are available, only one thread can process an order match at a time. Thus, having an extra core did not help much as it would just end up waiting for the other core to finish processing the client request before moving on to the next request from another thread. This contention limits the scalability of our server.

2. **Amdahl's Law**
  From Amdahl's Law, we can see that the overall performance can be improved by speeding up processes that can be done concurrently. Similarly, having large parts of the program that are sequential limits the total time we can save when optimizing the system and adding new cores. In our implementation, the order matching logic is inherently sequential, as orders must be matched in a specific sequence based on price and time priority, serving as a bottleneck for our matching server.

3. **Thread Management Overhead**
  Managing multiple threads can introduce overhead that diminishes the performance gains from an extra core, especially if the workload per request is not very heavy. Specifically, cores have to share resources. As a result, we can see that although the averages were not significantly different, the average throughput decreased slightly as we increased the number of cores.

4. **I/O vs. CPU Bound**
  Since each operation is not load heavy, the server is primarily waiting on I/O operations (such as network communication and database transactions) rather than performing CPU-intensive computations. Our implementation uses database sessions for all order operations, which introduces I/O wait times. Thus, adding more CPU cores did not lead to significant throughput improvements.

## Conclusion
Our exchange matching server does not exhibit the scalability characteristics we initially expected. Despite increasing the computational resources available to the server, performance metrics remained largely unchanged. This indicates that our current implementation has limitations that prevent it from effectively utilizing additional CPU cores.
