# Task 3: Streaming LLM gateway with PII redaction

An independent FastAPI/httpx SSE proxy with a deterministic local provider.
It parses generation deltas, redacts supported email/SSN/card patterns across
arbitrary delta and network boundaries, and incrementally emits safe text.
No paid APIs, keys, frontend, unified demo, or Task 4 behavior is involved.
Tasks 1 and 2 are unchanged.

## Run and test

From the repository root, with Python 3.11+ and the activated virtual environment:

```powershell
python -m pip install -e ".[dev]" -r task_03_streaming/requirements.txt
```

Terminal A, local provider:

```powershell
python -m task_03_streaming --mock --delay 0.05
```

Terminal B, gateway:

```powershell
python -m task_03_streaming
```

Terminal C, streaming request (PowerShell; `-N` disables curl output buffering):

```powershell
$body = '{"prompt":"demo","stream":true}'
$body | curl.exe -N -sS http://127.0.0.1:8084/v1/generate -H 'Content-Type: application/json' --data-binary '@-'
```

The decoded content is:

```text
Hello there. Email: [REDACTED]. SSN: [REDACTED]. Card: [REDACTED]. End.
```

The fixture also has a trailing space. The wire consists of SSE `data:` events
containing JSON deltas, ending with `data: [DONE]`. Use `prompt: normal` for normal
UTF-8 text or `prompt: large` for repeated normal text. These prompt names select
mock fixtures; they are not real model generation. Other prompts select `demo`.
`--repeats` controls the mock's large fixture, default 2000; `--delay` is the
requested seconds per generation delta, default 0.01. OS timer resolution affects
very small delays. Both services support `--host`, `--port`, and `--help`, default
to loopback, and stop with Ctrl+C.

```shell
python -m pytest task_03_streaming/tests -q
python -m pytest -q
python -m task_03_streaming.benchmark --runs 5 --delay 0.05 --output task_03_streaming/benchmark_results.json
```

The benchmark starts and cleans up its own local services on available ports.
It needs no manually running provider. See `BENCHMARKS.md` and the raw JSON for
actual measurements; the memory run intentionally uses tracemalloc and takes
longer than normal uninstrumented filtering.

## Contract and architecture

`POST /v1/generate` accepts exactly `{"prompt": "...", "stream": true}`;
`stream` defaults to true, the prompt is a strict string up to 2048 characters,
and unknown request fields are rejected. The upstream request uses that same
shape. There are no caller credentials or headers forwarded upstream.

```text
HTTP request -> async provider POST -> raw available network bytes
  -> bounded UTF-8 SSE framing -> strict JSON delta schema
  -> email-token holdback -> numeric-run holdback
  -> fresh sanitized JSON delta -> SSE client
```

Each supported upstream event is a single-choice text delta:

```text
data: {"choices":[{"delta":{"content":"generated text"}}]}

data: [DONE]

```

SSE is parsed incrementally, including UTF-8 and CR/LF/CRLF split across network
reads, multiline `data:` fields, comments and multiple events per chunk. Only
message data is interpreted; IDs, retry hints, comments and unknown SSE fields
are not relayed because they could contain unfiltered content. An unsupported
named event fails closed. The parser follows the framing rules in the
[SSE standard](https://html.spec.whatwg.org/multipage/server-sent-events.html).

The strict delta schema forbids extra JSON fields and supports exactly one
`choices[].delta.content` string per event, up to 8192 characters. This is an
explicit OpenAI-style **subset**, not universal OpenAI/provider compatibility.
Role-only deltas, finish-reason objects, usage objects, tool calls, logprobs and
other schemas need an explicit adapter and tests before use. Malformed or
unsupported content is never forwarded verbatim.

Output preserves decoded safe text, order, the SSE/JSON delta shape and `[DONE]`
completion semantics. It deliberately recombines delta boundaries and normalizes
JSON serialization and SSE line endings; it is not a byte-for-byte proxy.

## Stateful redaction and safety boundary

The email stage retains a maximal ASCII email-character token. It cannot release
`alice` early because a later `@example.test` could make that same token an email.
At a known lexical boundary or clean completion, it replaces matching addresses
and feeds the remaining text to the numeric stage. The numeric stage retains
digits and possible grouping spaces/tabs/hyphens until a definite boundary.
Only resolved safe output is released. State spans every delta and network read.

Supported patterns:

- Practical unquoted ASCII email addresses, including plus tags, dotted local
  parts, subdomains and alphabetic TLDs of 2–63 characters. The exact matcher is
  in `redaction.py`; it does not claim full RFC email or SMTPUTF8 coverage.
- SSNs as nine contiguous ASCII digits or `DDD-DD-DDDD`. No SSN validity lookup
  is used to excuse disclosure of a matching shape.
- Card-like sequences of 13–19 ASCII digits, contiguous or grouped with spaces,
  tabs or hyphens. Longer ambiguous numeric sequences are also redacted rather
  than leaking a card embedded inside them. No Luhn or issuer check is required.

Each detected span is replaced with `[REDACTED]`. Adjacent card-like values with
only numeric separators can merge into one conservative redacted span. Ordinary
text outside matching spans remains unchanged, including UTF-8. Dates, IDs or
other digit sequences that resemble supported PII can be false positives.

Quoted/Unicode email addresses, obfuscated PII, dotted/spaced SSNs, and semantic
or jurisdiction-specific PII are not guaranteed. This is a bounded pattern
guardrail, not a general production DLP system. The no-release guarantee applies
to the documented supported patterns; comprehensive PII recognition is partial.

An ambiguous token that exceeds a limit **terminates** the stream with a static
error. It is not split into unsafe pieces or flushed raw. An upstream failure,
timeout or missing completion discards the unresolved suffix. `[DONE]` is the
only clean completion signal that permits a final filtered flush.

## Bounds and latency tradeoffs

| Resource | Bound / behavior |
| --- | --- |
| Request body | 16 KiB |
| Prompt | 2048 characters |
| Accepted raw network chunk | 64 KiB; larger transport chunks fail closed |
| Processing slice | Up to 4096 available bytes; never waits to fill a slice |
| SSE event, including lines/comments | 32,768 Unicode characters |
| Decoded delta content | 8192 characters |
| Email candidate | 512 characters |
| Numeric candidate | 128 characters |
| Filter unresolved text | At most 640 characters before rejection |
| Provider connections | 20 pooled connections, 10 keepalive |
| Idle/connect/header timeout | Default 5 seconds |
| Streaming total deadline | Default 30 seconds |
| Cancellation cleanup | Shielded, at most 2 seconds per cleanup attempt |

These are per-stream application bounds, not whole-process RSS promises.
Python object overhead, HTTP transport buffers and concurrent requests add
memory. No response history or full generation is retained. ASGI backpressure
pauses provider consumption instead of filling an application queue.

Normal words can start streaming once the following delimiter resolves them.
A response starting with PII must wait until that candidate is safely resolved;
there is no honest zero-latency redaction of arbitrary future continuations.
Long unbroken normal words/URLs can also hit the conservative candidate limit.
There is no time-based unsafe flush. If a provider stalls on a potential address,
the deadline/error path drops it. The benchmark reports first **content output**,
not merely HTTP headers or a padding comment.

## Failures, disconnects and configuration

Before streaming starts, invalid requests receive static JSON HTTP 400/413,
provider failures/invalid status/content type receive 502, and connection/header
timeouts receive 504. After HTTP 200 has started, failures emit only:

```text
event: error
data: {"error":{"code":"stream_failed","message":"Upstream stream could not be safely completed"}}

```

No `[DONE]` follows an error. A client must treat an error or EOF without `[DONE]`
as incomplete. Already-released safe text cannot be recalled; unresolved suffixes
are discarded. Disconnection/task cancellation closes the upstream response.
The response wrapper also covers ASGI send failure before/after iteration begins.
Manual HTTPX streaming explicitly closes responses as required by the
[HTTPX streaming contract](https://www.python-httpx.org/async/).

Provider compression and redirects are rejected, retries and environment proxies
are disabled, and arbitrary upstream metadata/error bodies are never forwarded.
Application diagnostics are static categories without prompts, generated text,
credentials or exception values. CLI HTTP access logs are disabled.

| Environment variable | Default |
| --- | --- |
| `TASK3_PROVIDER_URL` | `http://127.0.0.1:8085/v1/generate` |
| `TASK3_IDLE_TIMEOUT` | `5` seconds, positive finite value up to 120 |
| `TASK3_TOTAL_TIMEOUT` | `30` seconds, positive finite value up to 300 |

Provider URL is operator-controlled HTTP(S), with no credentials/query/fragment.
No authentication or production identity is added in this task; keep both local
services on loopback. Deployment TLS, concurrency/ingress admission limits and
proxy buffering controls remain deployment concerns. Response headers request
`no-cache, no-transform` and disable common reverse-proxy buffering, but an
external proxy can still alter latency. Only Windows/Python 3.11.5 is validated.

See `VALIDATION.md` for the PASS/PARTIAL/FAIL checklist and test counts, and
`FILES.md` for the exact scoped change inventory. Task 4 remains unimplemented.
