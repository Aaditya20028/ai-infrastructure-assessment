# Actual Task 4 local measurements

Re-executed for the actual-tokenizer correction, separately from regression tests:

```shell
$env:TIKTOKEN_CACHE_DIR = Join-Path $PWD 'data\tiktoken-cache'
.venv/Scripts/python -u -m task_04_limiter.benchmark --operations 200 --runs 5 --output task_04_limiter/benchmark_results.json
```

Raw samples and assertions are in `benchmark_results.json`. Environment:
Windows 10 build 26200, Python 3.11.5, SQLite 3.41.2, FastAPI 0.162.0,
Uvicorn 0.54.0, HTTPX 0.28.1, Pydantic 2.14.2, tiktoken 0.12.0 / cl100k_base.
All databases were temporary
**on-disk files** using WAL, `synchronous=FULL` and a 5-second busy timeout.
No paid model endpoints or production credentials were involved.

## Ledger throughput

| Operation | Count | Elapsed | Observed throughput |
| --- | ---: | ---: | ---: |
| Sequential quota admissions | 200 | 2.075 s | 96.39 admissions/s |
| Sequential reconciliations | 200 | 1.966 s | 101.71 reconciliations/s |

The storage-only workload uses synthetic 100-token reservations and 30-token
settlements; it measures ledger operations, not tokenizer throughput. Connections,
clock update, eviction, atomic quota check and durable commit are included.
Initialization is excluded. These are individual operation rates, not completed
LLM request throughput and not a production concurrency SLA.

## Admission correctness under contention

| Probe | Attempts | Admitted | Rejected | Final held units | Elapsed |
| --- | ---: | ---: | ---: | ---: | ---: |
| 8 threads / separate connections | 64 | 50 | 14 | 50,000 | 1.136 s |
| 4 synchronized spawned processes | 80 | 50 | 30 | 50,000 | 1.889 s |

Each attempt reserved 1000 tokens for a shared tenant. The script asserts both
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
| Success | Primary | 29.63 ms |
| HTTP 429 | Secondary | 44.76 ms |
| Delayed 3.2 seconds | Secondary | 3066.55 ms |

Slow-case measured samples were 3111.21, 3066.55 and 3057.99 ms. The routing
deadline is 3000 ms for the primary call, not a promise that the full HTTP
request finishes within 3000 ms: backup latency, durable ledger work and OS
scheduling add time. All slow results selected the secondary; no late primary
result was delivered. Gateway and mock usage are counted with the actual pinned
tokenizer; vocabulary loading is completed at service startup, outside these
request-latency measurements. Separate controlled-clock tests cover exact boundary ties,
early timer wakeups and noncooperative late-response races.

These are local mock-provider and filesystem measurements. They do not estimate
commercial model tokenization, billing, throughput, WAN latency, multi-host
scalability, or storage crash guarantees. Results will vary with OS scheduling,
SQLite build, disk, background load and security software. No numbers are inferred
by multiplying configured sleeps or substituting in-memory counters.
