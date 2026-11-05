# Actual local benchmark results

Executed, not estimated:

```shell
.venv/Scripts/python -u -m task_03_streaming.benchmark --runs 5 --delay 0.05 --output task_03_streaming/benchmark_results.json
```

Raw samples, versions, counters and output hashes are in `benchmark_results.json`.
Environment: Windows 10 build 26200, Python 3.11.5, FastAPI 0.162.0, Uvicorn
0.54.0, HTTPX 0.28.1 and Pydantic 2.14.2. The benchmark launches real provider
and gateway subprocesses and uses loopback HTTP. Each case has one discarded
warmup and five measured requests with a reused client. Server startup is excluded.

## Latency

All values below are medians in milliseconds. First output means receipt of the
first nonempty, parsed content delta, not headers. Total means stream completion
and response closure. The gap column is the median of each run's largest gap
between nonempty content events.

| Case | First output | Total | Largest inter-output gap |
| --- | ---: | ---: | ---: |
| Direct mock, normal text | 76.47 | 298.78 | 63.51 |
| Gateway, normal text | 84.80 | 312.70 | 62.85 |
| Gateway, PII fixture | 86.02 | 799.59 | 267.26 |

The normal fixture emits five generation deltas; the PII fixture emits fourteen.
The PII gap includes the deliberate wait for whole sensitive candidates to be
resolved. Output begins before generation ends in both gateway cases. Cases are
sequential, unpaired local samples; subtracting their medians is not a precise
per-request gateway overhead estimate. These are not production/network SLAs.

The Windows monotonic clock resolution was 15.625 ms. An initial 10 ms mock-delay
trial ran much earlier than the requested delay during I/O activity. A separate
200 ms probe confirmed normal longer-delay behavior. The recorded run therefore
uses 50 ms requested generation delays. Actual scheduling remains OS-dependent;
the table contains measured client times rather than multiplying a requested
delay to invent a total.

## Memory behavior

The same script measures **in-process SSE parsing, strict delta validation and
redaction**, hashing/discarding output rather than retaining the generation.
It reuses a fixed normal-text frame, warms caches, runs garbage collection, and
starts a fresh tracemalloc session for each workload.

| Source characters | SSE wire bytes processed | Peak traced bytes | Maximum filter holdback | Maximum SSE pending characters |
| ---: | ---: | ---: | ---: | ---: |
| 131,040 | 160,020 | 6,644 | 6 | 254 |
| 2,097,056 | 2,560,828 | 6,620 | 6 | 254 |

The approximately 16-fold growth in input did not produce corresponding retained
pipeline growth in these measured workloads. The configured safety limits are
larger than these typical observed candidates; adversarial event/token limits
are separately tested to terminate safely.

This is not gateway RSS, allocator-reserved memory, OS socket memory, HTTPX/ASGI
buffer memory, concurrency scaling, or a worst-case Python-object allocation
measurement. It verifies the instrumented streaming pipeline without full-output
retention. The traced workloads took 2.57 and 30.39 seconds; tracing overhead makes
these timings unsuitable as a server throughput benchmark. No whole-process
memory or production-throughput claim is made.
