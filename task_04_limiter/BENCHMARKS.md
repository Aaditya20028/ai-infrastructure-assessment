# Actual Task 4 local measurements

Executed after Task 4's tests passed, separately from regression tests:

```shell
.venv/Scripts/python -u -m task_04_limiter.benchmark --operations 200 --runs 5 --output task_04_limiter/benchmark_results.json
```

Raw samples and assertions are in `benchmark_results.json`. Environment:
Windows 10 build 26200, Python 3.11.5, SQLite 3.41.2, FastAPI 0.162.0,
Uvicorn 0.54.0, HTTPX 0.28.1, Pydantic 2.14.2. All databases were temporary
**on-disk files** using WAL, `synchronous=FULL` and a 5-second busy timeout.
No paid model endpoints or production credentials were involved.

## Ledger throughput

| Operation | Count | Elapsed | Observed throughput |
| --- | ---: | ---: | ---: |
| Sequential quota admissions | 200 | 1.197 s | 167.09 admissions/s |
| Sequential reconciliations | 200 | 1.113 s | 179.76 reconciliations/s |

Each admission reserved 100 units; each reconciliation charged 30. Connections,
clock update, eviction, atomic quota check and durable commit are included.
Initialization is excluded. These are individual operation rates, not completed
LLM request throughput and not a production concurrency SLA.

## Admission correctness under contention

| Probe | Attempts | Admitted | Rejected | Final held units | Elapsed |
| --- | ---: | ---: | ---: | ---: | ---: |
| 8 threads / separate connections | 64 | 50 | 14 | 50,000 | 0.828 s |
| 4 synchronized spawned processes | 80 | 50 | 30 | 50,000 | 1.018 s |

Each attempt reserved 1000 units for a shared tenant. The script asserts both
admission count and ledger sum; both probes stopped exactly at the quota. Thread
time includes connection/constructor setup. Process time includes Python spawn
and synchronization, and all four worker PIDs participated. A fixed test clock
prevents expiration from changing the contention experiment.

## End-to-end local routing latency

Three independent HTTP processes run for each case: gateway, primary fixture
and secondary fixture. Times include client HTTP exchange, quota admission,
provider request(s), usage checks and reconciliation; service startup is excluded.
The fast cases discard one warmup and report five measured samples. The slow
case reports three real timeout samples without an extra slow warmup.

| Primary behavior | Selected provider | Median gateway latency |
| --- | --- | ---: |
| Success | Primary | 22.77 ms |
| HTTP 429 | Secondary | 32.62 ms |
| Delayed 3.2 seconds | Secondary | 3056.42 ms |

Slow-case measured samples were 3074.32, 3056.42 and 3020.75 ms. The routing
deadline is 3000 ms for the primary call, not a promise that the full HTTP
request finishes within 3000 ms: backup latency, durable ledger work and OS
scheduling add time. All slow results selected the secondary; no late primary
result was delivered. Separate controlled-clock tests cover exact boundary ties,
early timer wakeups and noncooperative late-response races.

These are local mock-provider and filesystem measurements. They do not estimate
commercial model tokenization, billing, throughput, WAN latency, multi-host
scalability, or storage crash guarantees. Results will vary with OS scheduling,
SQLite build, disk, background load and security software. No numbers are inferred
by multiplying configured sleeps or substituting in-memory counters.
