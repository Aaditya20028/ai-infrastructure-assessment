# Task 4 validation and requirement evaluation

Environment: Windows/Python 3.11.5, SQLite 3.41.2; dependency versions are pinned
in `requirements.txt`. No changes were made to Tasks 1–3 or shared configuration.
No frontend, combined demo or final evaluator workflow was added.

## Actual test runs

```shell
.venv/Scripts/python -u -m pytest task_04_limiter/tests -q -o faulthandler_timeout=40
# 85 passed in 23.61 seconds
.venv/Scripts/python -u -m pytest -q -o faulthandler_timeout=40
# 341 passed in 41.90 seconds
```

No skips, expected failures or warnings were reported. Test counts:

| Group | Passed | Evidence |
| --- | ---: | --- |
| Task 4 contract/auth | 22 | Byte counting, output/usage consistency, strict validation, verified tenant keys, invalid config |
| Task 4 SQLite | 15 | Exact limit, rolling eviction, active holds, tenant separation, restart, real 8-thread/4-process contention, WAL/index/version/busy handling |
| Task 4 deadline races | 2 | Early timer wakeup recheck and response exactly at deadline |
| Task 4 gateway | 42 | Primary success, 429/timeout fallback, late primary discarded, failed/invalid provider errors, HTTP concurrency, three cancellation stages, accounting/persistence and no-forward denials |
| Task 4 real HTTP integration | 4 | Three independent CLI services: primary success, 429, actual 3000 ms timeout, failed backup |
| Task 1 unchanged | 96 | All SDK/stdio regressions |
| Task 2 unchanged | 97 | All auth/policy/proxy regressions |
| Task 3 unchanged | 57 | All PII/SSE/streaming lifecycle regressions |
| Shared existing tests | 6 | Shared mock HTTP checks and on-disk SQLite probe |
| **Total** | **341** | Full pytest suite |

Tests use temporary on-disk SQLite databases, generated mock credentials and
controllable clocks. The process test synchronizes four spawned workers at a
barrier before competing for quota. Live HTTP timeout testing actually waits
for the strict 3000 ms deadline; other deadline races advance a fake clock rather
than sleeping. Cancellation tests exercise admission before thread commit,
provider work, and cancellation after actual reconciliation has committed.

Development tests caught pre-read mock response handling and the classification
of malformed compressed responses. Both were corrected before the passing runs.
Actual local benchmarks were then executed independently; see `BENCHMARKS.md`
and the raw JSON samples. No test or benchmark success is inferred.

## Exact assessment criteria

| Requirement | Evaluation | Evidence and contract |
| --- | --- | --- |
| 1. Resilient completion-routing module | PASS | Strict request boundary, authenticated independent FastAPI gateway and separate deterministic providers |
| 2. 50000-token rolling 60-second quota per tenant API key | PASS under documented mock contract | UTF-8 byte token units; active holds plus settlements in `(now-60, now]`; exact 50000 accepted, excess rejected; tenant identity comes only from verified key mapping |
| 3. On-disk SQLite | PASS | File-backed WAL ledger, schema version 1, restart tests and rejected memory database paths |
| 4. Primary HTTP 429 triggers backup | PASS | Spy and live HTTP tests; immediate single secondary attempt, one logical reservation |
| 5. Primary exceeds 3000 ms triggers backup | PASS | Monotonic deadline fixed at 3.0 seconds, early wakeup/tie checks, fake-clock late-primary test, live 3.2-second mock and measured timeout samples |
| 6. Standardized sanitized gateway errors | PASS | Public code/message/generated request ID; no upstream body/URL, API key, traceback or internal exception details in responses/logs |
| 7. Async concurrency, races, eviction and graceful fallback | PASS | Atomic transactions, real multi-process test, active holds never age out mid-request, cancellation-safe DB calls, late primary result cannot settle or replace backup |

## Requested automated scenarios

| Scenario | Result | Test evidence |
| --- | --- | --- |
| 1–3. Under, exactly at, above limit | PASS | Storage boundary tests and HTTP exact-limit/no-forward assertions |
| 4–5. Rolling boundary and expired eviction | PASS | 159.999/160 clock boundary; no calendar-minute reset; exact expired row count |
| 6. Two independent tenants | PASS | Storage and authenticated HTTP tenant tests; verified key aliases also tested |
| 7–8. Concurrent requests/connections/processes | PASS | 80 HTTP admissions, 8 threads, 4 synchronized real spawned workers; never above 50000 |
| 9. Persistence across restart | PASS | Store reopen and separate FastAPI lifespan tests; active holds also survive |
| 10–11. Primary success / HTTP 429 | PASS | Backup not contacted on success; exactly two attempts for 429 |
| 12–13. 3000 ms timeout / late primary | PASS | Exact injected deadline, real HTTP timeout, cancelled primary released late without response or ledger overwrite |
| 14–16. Backup/both unavailable/unexpected errors | PASS | Sanitized HTTP 503/502/504 cases, no stack/URL/secret reflection |
| 17. Cancellation and cleanup | PASS | Admission thread completion known before cleanup; active work cancelled; post-commit actual charge not overwritten |
| 18. No incorrect double charge for fallback | PASS | One ledger row and winning usage for 429/timeout; full single reserve on failed logical request |
| 19. Expiry cannot corrupt ongoing reservation | PASS | Long-running holds survive multiple windows, then receive a new settlement window |
| 20. Existing suite stays working | PASS | All 250 Task 1–3 tests plus six shared tests pass |

## Declared partial scope and limitations

| Area | Evaluation | Limit |
| --- | --- | --- |
| Real native-provider tokenizer / aggregate retry billing | PARTIAL | Mock byte-unit logical quota is exact; unknown commercial-model overhead and paid primary work after timeout are not claimed to be bounded |
| Automatic crash/orphan recovery | PARTIAL | Orphan holds persist fail closed; verified operator reconciliation is required instead of an unsafe automatic TTL |
| Multi-host distributed storage and clock failure | PARTIAL | Local shared SQLite file only; wall-clock rollback is clamped, forward jumps remain a host-clock assumption |
| Arbitrarily noncooperative coroutines | PARTIAL | Late results cannot overwrite response/accounting; Python cannot forcibly kill a coroutine that suppresses cancellation forever |
| Cross-platform/production load validation | PARTIAL | Real measurements on Windows with local mocks and this SQLite build; no WAN, native-model or multi-host SLA |

Git commit/push state is reported separately after the actual attempt and remote
SHA verification. This file does not claim remote publication.
