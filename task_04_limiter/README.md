# Task 4: Durable token limiter and model fallback router

An independently runnable FastAPI completion gateway with an on-disk SQLite
reservation ledger, authenticated tenant keys, and two configurable local model
fixtures. The quota is **50,000 accounted token units per rolling 60 seconds**
per authenticated tenant. Primary HTTP 429 or a strict 3000 ms deadline triggers
one backup attempt. Tasks 1–3 remain unchanged. No frontend or combined demo is
included; these task-specific instructions supersede its original scaffold.

## Architecture

```text
Bearer key -> verified tenant digest -> strict request validation
    -> atomic on-disk quota reservation
    -> primary (3000 ms) -> secondary only on primary 429/timeout
    -> validate winning text/usage -> reconcile one reservation -> response
```

- `models.py` / `auth.py`: strict contracts, required mock credentials and
  server-side tenant identity. Body/header tenant claims cannot select a quota.
- `accounting.py`: one documented byte-based token contract and usage checks.
- `storage.py`: versioned schema, WAL, atomic admission, reconciliation/eviction
  and cancellation-safe thread calls around standard-library sqlite3.
- `providers.py`: bounded async forwarding, explicit fallback policy and
  deadline races that never wait for late primary cancellation to begin backup.
- `app.py`: composition and sanitized public error responses.

## Install, run and send a request

From the repository root with Python 3.11+ and an activated `.venv`:

```powershell
python -m pip install -e ".[dev]" -r task_04_limiter/requirements.txt
```

Terminal A, primary fixture:

```powershell
python -m task_04_limiter --service primary
```

Terminal B, secondary fixture:

```powershell
python -m task_04_limiter --service secondary
```

In the gateway PowerShell session, generate a local key and configure its tenant:

```powershell
$tenantKey = python -c "import secrets; print(secrets.token_urlsafe(32))"
$keyMap = @{}
$keyMap[$tenantKey] = 'tenant-a'
$env:TASK4_API_KEYS = $keyMap | ConvertTo-Json -Compress
$env:TASK4_DATABASE = Join-Path $PWD 'data\task4_quota.sqlite3'
python -m task_04_limiter
```

The last command runs in the foreground and prints Uvicorn startup diagnostics.
To issue requests from the same configured session, use this hidden background
launch **instead** of the foreground command, then allow startup to complete:

```powershell
$gatewayProcess = Start-Process -FilePath "$PWD\.venv\Scripts\python.exe" -ArgumentList '-m','task_04_limiter' -WorkingDirectory $PWD -WindowStyle Hidden -PassThru
```

Send a request from that session:

```powershell
$body = '{"prompt":"hello","max_output_tokens":64}'
$body | curl.exe -sS -i http://127.0.0.1:8086/v1/complete -H "Authorization: Bearer $tenantKey" -H 'Content-Type: application/json' --data-binary '@-'
```

Success includes `request_id`, `text`, `provider` (`primary` or `secondary`),
`fallback_reason` (null, `primary_rate_limit` or `primary_timeout`), and measured
`usage` with `counting_method: utf8_bytes_v1`. No provider URL or API key is
included. `max_output_tokens` is a strict integer, defaults to 256, and must be
1..50000; `prompt` is a strict string up to 50000 characters. Unknown fields,
including `tenant` and `tenant_id`, are rejected. The HTTP body limit is 256 KiB.

Defaults: gateway `127.0.0.1:8086`, primary `127.0.0.1:8087`, secondary
`127.0.0.1:8088`; all use `/v1/complete`. Stop foreground services with Ctrl+C;
stop the background gateway with `Stop-Process -Id $gatewayProcess.Id`.

To exercise fallback, restart only the primary fixture with one of:

```powershell
python -m task_04_limiter --service primary --behavior rate_limit
python -m task_04_limiter --service primary --behavior slow --delay 3.2
```

The secondary can similarly use `--behavior unavailable` to test a failed backup.
Services support `--host`, `--port`, `--behavior ok|rate_limit|slow|unavailable`
and `--delay`. The mock returns deterministic ASCII text and exact local usage;
it makes no real model calls. Its output is truncated to the requested byte-unit
budget. Provider behavior is operator configuration, not a client request field.

## Exact token-accounting contract

The local fixtures define **one accounted token unit as one UTF-8 byte** of the
prompt or generated text. Input is counted before admission; the reservation is:

```text
UTF8_byte_length(prompt) + max_output_tokens
```

`max_output_tokens` is the maximum output **byte units** for these mocks, not a
claim about an arbitrary commercial model's tokenizer. UTF-8 bytes provide a
conservative prompt proxy for common byte-level tokenizers, but hidden system
messages, template overhead and other tokenizers are not modeled. The response
explicitly labels the counting method. A real provider needs a validated
tokenizer/overhead adapter and output-bound contract before using these quotas.

Success recomputes input/output byte counts from validated prompt and result.
An optional provider usage report must match exactly. Missing usage uses measured
bytes; negative, inconsistent or excessive usage/output fails closed. Provider
responses are capped at 300000 bytes, must be JSON, and cannot be compressed or
redirected. Caller credentials, cookies and custom headers are not forwarded.

The quota is for **one logical gateway request and its winning completion**, not
aggregate provider billing across multiple attempts. A timed-out primary may
still incur external provider work/billing; that physical aggregate is outside
this explicitly defined mock quota. No claim of bounding real paid-provider
billing across fallback is made. This distinction is necessary when usage from
an abandoned primary is unknown.

### Reservation, reconciliation and window policy

| Stage | Ledger treatment |
| --- | --- |
| Admission | Reserve conservative input + full output maximum before any provider call; reject if active holds + unexpired settled units + new hold would exceed 50000 |
| Primary 429 / timeout | Reuse the same logical hold for one backup; no second reservation or duplicate input charge |
| Success | Replace the hold with actual winning input + output units, timestamped at reconciliation |
| Failed/invalid providers or cancellation | Settle the full reservation once, conservatively retaining unknown work; do not repeatedly refund failures |
| Repeated cleanup | No-op after settlement; never overwrite or double-charge an already reconciled winner |
| Expiration | Evict settled records at `settled_at <= now - 60`; a settlement is charged in `(now - 60, now]` |
| Ongoing request older than 60 seconds | Keep its full active hold; elapsed age alone never grants another request that budget |
| Crash/orphan reservation | Persist the active hold; do not automatically expire unknown in-flight work |

Usage is attributed to completion/reconciliation time, with full active holds
before that moment. This is a conservative true sliding window, not a fixed
minute counter or a timestamp at admission that might expire mid-request.
Exactly 50000 is admitted; 50001 is rejected. Distinct configured tenants have
independent ledgers; multiple valid keys mapped to the same tenant deliberately
share one quota. Quota limits/window are constants, not client-configurable.

Cancellation during a threaded admission is deferred until its transaction has
a known outcome; cleanup then settles the known request ID. Cancellation after
a successful reconciliation cannot replace actual usage with another charge.
No network call occurs while a SQLite transaction is held. A cancellation or
hard process crash cannot silently release an ambiguous reservation.

## SQLite schema, initialization and recovery

The database is a dedicated on-disk file, default `data/task4_quota.sqlite3`.
`:memory:` and URI-memory databases are rejected. Runtime `.sqlite3`, `-wal`
and `-shm` files are ignored by Git, never submission artifacts.

Schema version 1 (`PRAGMA user_version=1`) is initialized atomically at startup:

| Table | Fields / purpose |
| --- | --- |
| `reservations` | `request_id` primary key; hashed `tenant`; `reserved`; charged/held `units`; `state` active/settled; `created_at`; nullable `settled_at` |
| `quota_clock` | Singleton `latest` observed clock value, clamped across workers to prevent backward-clock reuse |

Checks constrain units to `0 <= units <= reserved <= 50000`, require positive
reservations, and enforce active/settled timestamp consistency. Indexes cover
tenant sums and settled expiration (`settled_at` partial index). `storage.py`
contains the authoritative DDL and transition SQL. All SQL values are bound
parameters. Raw API keys, prompts, completion text and provider URLs are not
stored in the ledger.

Initialization supports a new/version-0 dedicated database and existing version
1. Unknown schema versions fail startup; no guessed destructive migration runs.
Each operation opens its own connection with a 5-second busy timeout and
`synchronous=FULL`; WAL is enabled. `BEGIN IMMEDIATE` serializes the
evict/count/check/insert transaction across threads and processes on the same
host. Read/update transactions use the same consistent clock. Busy or unavailable
storage returns a sanitized 503 and fails admission closed.

An orphan hold is an availability tradeoff, not an invisible quota bypass.
After proving that **all work for that request has stopped**, an operator may
use `QuotaStore.settle(request_id)` to conservatively charge its full reservation
from recovery time. There is no public reset endpoint or automatic unsafe TTL.
Never delete live reservations or reset the database while other workers run.
Storage failure during reconciliation leaves the full hold rather than granting
unaccounted capacity.

Wall-clock time is shared/persisted and backward changes are clamped. Forward
clock jumps still affect wall-clock windows; use a trustworthy host clock. WAL
requires local shared storage on one host, not independently copied databases or
a network filesystem. References: [SQLite transactions](https://www.sqlite.org/lang_transaction.html),
[WAL](https://www.sqlite.org/wal.html), and
[busy timeout](https://www.sqlite.org/pragma.html#pragma_busy_timeout).

## Strict fallback and public errors

The primary's **3000 ms monotonic deadline covers connect/pool wait, headers,
body and response validation**; it does not include quota admission time.
Early timer wakeups re-check the clock. A response at or after the deadline
loses the race. Backup starts without waiting for a cancelled primary to finish
cleanup. Primary tasks cannot write the client response or reconcile usage;
late results/errors are discarded and retrieved without logging sensitive data.

Only primary HTTP 429 or a timeout triggers the secondary. No Retry-After wait,
same-provider retry, or fallback for network errors, HTTP 408/5xx, malformed JSON
or usage violations is added. Secondary gets one explicit deadline, default
3 seconds; it has no tertiary fallback. HTTPX is expected to cooperate with
cancellation. Shutdown cancels tracked tasks and waits at most one second before
closing the HTTP client; Python cannot forcibly kill an arbitrarily malicious
coroutine that suppresses cancellation forever.

Every application completion error has the same public shape:

```json
{"error":{"code":"quota_exceeded","message":"Token quota exceeded","request_id":"server-generated-id"}}
```

| Failure | HTTP | Public code |
| --- | --- | --- |
| Invalid/missing/duplicate bearer credentials | 401 | `unauthorized`, bearer challenge |
| Invalid request / body too large | 400 / 413 | `invalid_request` |
| Logical quota would exceed 50000 | 429 | `quota_exceeded` |
| SQLite unavailable or reconciliation unavailable | 503 | `quota_unavailable` |
| Provider HTTP 429/503 surfaced after policy | 503 | `providers_unavailable` |
| Secondary deadline/timeout | 504 | `provider_timeout` |
| Other provider/network/unexpected provider failure | 502 | `provider_error` |
| Invalid/oversize response or inconsistent usage | 502 | `invalid_provider_response` |
| Unexpected gateway failure | 500 | `gateway_error` |

No raw upstream error body, exception value, stack trace, credential, database
path or provider URL is returned. Request IDs are server-generated random UUIDs,
not trusted client claims. Logs use static categories; CLI access logs are off.
This task is non-streaming routing/accounting and does not silently compose
Task 3's PII filter into its completion response.

## Configuration, tests and limits

| Environment variable | Default / requirement |
| --- | --- |
| `TASK4_API_KEYS` | Required nonempty JSON map: opaque 32+ URL-safe-character key -> tenant label |
| `TASK4_DATABASE` | `data/task4_quota.sqlite3`, on disk |
| `TASK4_PRIMARY_URL` | `http://127.0.0.1:8087/v1/complete` |
| `TASK4_SECONDARY_URL` | `http://127.0.0.1:8088/v1/complete` |
| `TASK4_SECONDARY_TIMEOUT` | `3`, positive finite seconds up to 30 |

Provider URLs are operator-controlled HTTP(S), without credentials/query/fragment.
Redirects, environment proxies and automatic retries are disabled. Twenty pooled
provider connections are allowed. No paid keys, production identity provider,
TLS termination, key-expiry service, automatic orphan recovery, distributed
multi-host store, or native commercial-model tokenizer is claimed. Keep fixtures
on loopback/private networks. Keys are configurable local shared secrets; rotate
configuration and restart to revoke them. Only Windows/Python 3.11.5/SQLite 3.41.2
was exercised. Direct dependencies are pinned; transitives are not hash-locked.

```shell
python -m pytest task_04_limiter/tests -q
python -m pytest -q
python -m task_04_limiter.benchmark --operations 200 --runs 5 --output task_04_limiter/benchmark_results.json
```

The benchmark manages its own isolated services, random mock key and temporary
on-disk databases. It measures actual local throughput, synchronized thread/
process admission correctness and fallback latency, including real 3-second
timeouts. See `BENCHMARKS.md`, raw `benchmark_results.json`, `VALIDATION.md` and
`FILES.md` for measured results, requirement evaluation and scoped changes.
