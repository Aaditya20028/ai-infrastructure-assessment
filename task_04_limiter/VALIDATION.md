# Task 4 tokenizer correction — validation record

The previous UTF-8-byte implementation did not satisfy actual token counting.
It has been replaced in code by tiktoken 0.12.0 with explicit cl100k_base.
Earlier byte-based results are historical and are superseded by this record.

## Actual executions

Environment: Windows, Python 3.11.5, SQLite 3.41.2, tiktoken 0.12.0,
FastAPI 0.162.0, Uvicorn 0.54.0, HTTPX 0.28.1, Pydantic 2.14.2.
Tokenizer vocabulary was warmed into an ignored local cache first.

```powershell
$env:TIKTOKEN_CACHE_DIR = Join-Path $PWD 'data\tiktoken-cache'
python -c "from task_04_limiter.tokenization import encoding; encoding()"
python tools/verify_independence.py --task 4
# 103 passed in 38.81 seconds; Task 4 only, sibling/demo imports blocked
python -m pytest -q -o faulthandler_timeout=60
# 374 passed in 79.60 seconds
```

Before the final additional admission test, the direct Task 4 suite also passed
102 tests in 39.09 seconds. The final isolated run above includes all 103.
No skips, expected failures or warnings were reported in the passing runs.

| Group | Passed | Evidence |
| --- | ---: | --- |
| Task 4 tokenizer/contracts/auth | 28 | Known token IDs, byte-vs-token distinction, special spellings as ordinary text, Unicode-safe token-prefix truncation, strict usage/auth |
| Task 4 storage | 16 | Rolling boundary, exact quota, persistence, 8-thread/4-process concurrency, active holds, WAL/indexes and safe version-1 migration |
| Task 4 deadlines | 2 | Early timer wakeup and exact 3000 ms tie behavior |
| Task 4 gateway | 43 | Token-based admission/reconciliation, actual 50000-token boundary, low-token/high-byte admission, fallback, cancellation and errors |
| Task 4 real HTTP | 4 | Separate gateway/primary/secondary CLI processes, success, 429, actual 3000 ms timeout, failed backup |
| Both mock providers, token budgets | 10 | Independent tiktoken reference counts and actual output-token caps 1/2/3/4/10 |
| Tasks 1–3, unchanged | 250 | All original suites pass |
| Shared, architecture and optional demo | 21 | Includes real optional --all run with corrected token-based rejection |
| **Full total** | **374** | Complete regression suite |

## Correction requirements

| Requirement | Result | Evidence |
| --- | --- | --- |
| Count genuine tokenizer-produced token IDs | PASS | len(cl100k_base.encode_ordinary(text)); hello world IDs [15339,1917], count 2 rather than 11 bytes |
| Pin and document tokenizer/encoding | PASS | tiktoken==0.12.0 in pyproject and task requirements; fixed cl100k_base; response identifies counting method/encoding |
| Same counting in gateway and both mocks | PASS | Shared Task 4 tokenization helper; mock usage checked independently against installed tiktoken |
| Reserve counted input + max_output_tokens | PASS | Pre-forward reservation; exact-token boundary fixtures use 49999 input IDs plus one output token |
| Reconcile actual counted input + output | PASS | Recount returned text; optional reported usage must match; missing usage uses tokenizer counts |
| max_output_tokens limits tokens, not bytes | PASS | One-token mock output is Mock, four bytes; token-prefix truncation and re-count enforce cap, including Unicode tests |
| Preserve 50000-token rolling 60-second quota | PASS | Original atomic ledger invariant retained; tokens held for active requests; exact rolling expiration and no fixed-minute reset |
| Independent authenticated tenants | PASS | Verified key mapping and stable tenant digests; separate quota tests and aliases retained |
| On-disk persistence and concurrent admission | PASS | SQLite WAL/FULL, BEGIN IMMEDIATE, separate connections/processes; no over-admission |
| Correct expired-record eviction | PASS | Only settled rows at cutoff are evicted; active holds never age out mid-request |
| Preserve fallback/error/cancellation behavior | PASS | Original 429/3000 ms policy and cleanup tests pass; no duplicate logical fallback charge |
| Safe upgrade from byte-based ledgers | PASS, conservative legacy transition | Schema 2 labels legacy rows and preserves their amounts; no invented conversion or quota reset; old settlements expire normally and active holds remain protected |
| Task independence | PASS | Corrected Task 4 passes in isolation; Tasks 1–3 source/tests/docs unchanged |

## Migration and scope limits

All new admissions and settlements use real token counts. Existing version-1
rows cannot be re-tokenized because prompts and outputs were deliberately never
stored. Their byte amounts remain conservative upper-bound holds under
legacy_utf8_bytes_v1, not falsely relabelled token measurements. They expire or
receive explicit full settlement through the existing safe policy. New rows are
marked tiktoken_cl100k_base_v1. Migration never clears quota; mixed-version
workers/providers must be stopped and restarted together.

cl100k_base is a real tokenizer, not a promise of exact commercial-model billing.
The API counts plain prompt/output text with this explicit encoding, excludes
unknown chat/system overhead, and counts one logical winning completion rather
than unknown paid-provider work after a timeout. Other encodings/provider usage
contracts need a deliberate adapter. Orphan holds, single-host SQLite and host
clock assumptions remain as documented in README; those policies are unchanged.

First tokenizer use needs the public hash-verified vocabulary download or a
pre-warmed cache. No paid API key is required. Missing assets fail startup; no
byte/word approximation is substituted. Cache assets are not committed.

Actual benchmarks were refreshed with the tokenizer implementation and its
version in the raw report. See BENCHMARKS.md and benchmark_results.json. The
storage-only measurements allocate synthetic token amounts; HTTP cases use real
counting in gateway/providers. No native-provider accuracy, production performance
or transitive dependency hash-lock claim is made.

The precise correction inventory is in FILES.md. Git publication is reported
separately after the actual push attempt and independent remote SHA lookup.
