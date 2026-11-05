# Task 2: HTTP/JSON-RPC MCP security gateway

A lightweight FastAPI reverse proxy for `tools/list` and `tools/call`, backed by
an independent deterministic HTTP mock. Opaque configured tokens authenticate
users; server-side configuration assigns each token the `admin` or `viewer`
role. No caller-supplied role or unverified JWT claim is trusted. Task 1 and
tasks 3–4 are unchanged. This README supersedes the original setup-only status
for Task 2.

## Architecture and policy

```text
Agent POST /mcp + bearer token
    -> bounded JSON-RPC parsing
    -> authenticate configured token (auth.py)
    -> authorize tool name (policy.py)
    -> one async HTTP forward (proxy.py)
    -> validate response envelope/ID -> return original response bytes
```

| Request | Admin | Viewer |
| --- | --- | --- |
| `tools/list` | Forward unchanged | Forward unchanged |
| `tools/call`, name begins with `admin_` | Forward | Deny before forwarding |
| `tools/call`, any other name | Forward | Forward |
| Other JSON-RPC method | Reject locally | Reject locally |

The prefix check is case-sensitive, exactly as specified. Unknown tools without
that prefix reach downstream for normal tool-not-found handling. Discovery is
not filtered: viewers see `admin_reset_key`, but cannot execute it. A viewer's
attempt to set `X-Role: admin` or `params.role` changes nothing.

The exact denial response for request ID `blocked` is:

```json
{"jsonrpc":"2.0","id":"blocked","error":{"code":-32001,"message":"Unauthorized Tool Call"}}
```

That response uses HTTP 403. The HTTP client must inspect the JSON-RPC body even
on non-2xx status codes.

## Setup and run

Run from the repository root with Python 3.11+ and an activated `.venv`:

```powershell
python -m pip install -e ".[dev]" -r task_02_security/requirements.txt
```

Generate local-only credentials in your PowerShell session. They are random on
every run, never embedded in source or written to a file:

```powershell
$adminToken = python -c "import secrets; print(secrets.token_urlsafe(32))"
$viewerToken = python -c "import secrets; print(secrets.token_urlsafe(32))"
$roleMap = @{}
$roleMap[$adminToken] = 'admin'
$roleMap[$viewerToken] = 'viewer'
$env:TASK2_TOKEN_ROLES = $roleMap | ConvertTo-Json -Compress
$env:TASK2_UPSTREAM_URL = 'http://127.0.0.1:8083/mcp'
```

The gateway refuses to start without a nonempty valid token map. Tokens must be
at least 32 URL-safe ASCII characters. Token maps may contain multiple tokens
for each role. Role names other than `admin` and `viewer` fail configuration.
These are mock bearer credentials, not production credentials.

In a second terminal, start the unauthenticated local fixture:

```powershell
python -m task_02_security --mock
```

In the configured terminal, start the gateway:

```powershell
python -m task_02_security
```

Gateway: `http://127.0.0.1:8082/mcp`; mock: `http://127.0.0.1:8083/mcp`.
Both default to loopback. Each CLI supports `--host`, `--port`, and `--help`.
To keep the terminal available for the example commands below, PowerShell can
launch the configured gateway with a hidden window; it inherits this session's
environment:

```powershell
$gatewayProcess = Start-Process -FilePath "$PWD\.venv\Scripts\python.exe" -ArgumentList '-m','task_02_security' -WorkingDirectory $PWD -WindowStyle Hidden -PassThru
```

Use either foreground launch or the hidden launch, not both on the same port.
Stop the foreground services with Ctrl+C; stop the background gateway with
`Stop-Process -Id $gatewayProcess.Id`.

Alternative ASGI entry points:

```shell
python -m uvicorn task_02_security.app:create_app --factory --host 127.0.0.1 --port 8082 --no-access-log
python -m uvicorn task_02_security.mock_downstream:create_mock_app --factory --host 127.0.0.1 --port 8083 --no-access-log
```

## Example requests

Run from the same configured PowerShell session while both services are running.
`curl.exe` writes response headers and JSON, including expected 401/403 errors:

```powershell
$list = '{"jsonrpc":"2.0","id":"catalog","method":"tools/list","params":{}}'
$list | curl.exe -sS -i http://127.0.0.1:8082/mcp -H "Authorization: Bearer $viewerToken" -H 'Content-Type: application/json' --data-binary '@-'

$reset = '{"jsonrpc":"2.0","id":"reset-1","method":"tools/call","params":{"name":"admin_reset_key","arguments":{}}}'
$reset | curl.exe -sS -i http://127.0.0.1:8082/mcp -H "Authorization: Bearer $adminToken" -H 'Content-Type: application/json' --data-binary '@-'
$reset | curl.exe -sS -i http://127.0.0.1:8082/mcp -H "Authorization: Bearer $viewerToken" -H 'Content-Type: application/json' --data-binary '@-'

$status = '{"jsonrpc":"2.0","id":0,"method":"tools/call","params":{"name":"get_status","arguments":{}}}'
$status | curl.exe -sS -i http://127.0.0.1:8082/mcp -H "Authorization: Bearer $viewerToken" -H 'Content-Type: application/json' --data-binary '@-'
$status | curl.exe -sS -i http://127.0.0.1:8082/mcp -H 'Content-Type: application/json' --data-binary '@-'
```

Expected outcomes in order: list HTTP 200 containing both tools; admin reset
HTTP 200 with `status: simulated` and `key_reset: true`; viewer reset HTTP 403
with code `-32001`; viewer status HTTP 200 with `status: ready`; missing token
HTTP 401 with code `-32000`. The reset fixture never generates or changes a key.
An unknown permitted tool returns the downstream JSON-RPC `-32602` unchanged.

## Configuration

| Environment variable | Default / rule |
| --- | --- |
| `TASK2_TOKEN_ROLES` | Required JSON object mapping opaque tokens to `admin` or `viewer` |
| `TASK2_UPSTREAM_URL` | `http://127.0.0.1:8083/mcp`; fixed by operator, never by client input |
| `TASK2_TIMEOUT_SECONDS` | `5`; positive finite total deadline, at most 120 seconds |
| `TASK2_MAX_REQUEST_BYTES` | `65536`; positive integer |
| `TASK2_MAX_RESPONSE_BYTES` | `1048576`; positive integer, enforced while reading downstream |

The downstream URL must be HTTP(S), without credentials, query, or fragment.
Redirects, environment proxy settings, and automatic retries are disabled.
There is one app-lifespan-managed async HTTP client with bounded connection
pooling. Caller Authorization/Cookie/custom headers and upstream Set-Cookie
are not propagated. Explicit requests also prevent backend cookies stored by
httpx from leaking into another caller's request.

Only JSON request bytes are forwarded; object formatting, metadata, arguments,
and request IDs remain unchanged. Successful downstream JSON responses and
JSON-RPC application errors are returned byte-for-byte after structural and
ID validation. Downstream non-200 HTTP statuses are sanitized gateway failures,
not blindly passed through. Only safe JSON content type is returned; arbitrary
backend headers are not relayed.

## Errors and safety

| Condition | HTTP | JSON-RPC error |
| --- | --- | --- |
| Malformed JSON, duplicate keys, invalid UTF-8, nonfinite numeric values | 400 | `-32700`, ID null |
| Invalid envelope, batch input, invalid/null/bool/fractional request ID | 400 | `-32600`, usable ID or null |
| Missing/malformed tool-call params/name/arguments | 400 | `-32602`, original ID |
| Missing/invalid bearer token or duplicate Authorization headers | 401 | `-32000`, original ID; `WWW-Authenticate: Bearer` |
| Viewer calls `admin_*` | 403 | `-32001`, `Unauthorized Tool Call`, original ID |
| Unsupported method | 400 | `-32601`, original ID |
| Oversize request | 413 | `-32600`, ID null |
| Downstream HTTP/network failure, bad content type/body/ID, oversize response | 502 | `-32002`, original ID |
| HTTPX timeout or total downstream deadline | 504 | `-32003`, original ID |
| Unexpected forwarding failure | 500 | `-32603`, sanitized message, original ID |

IDs preserve both value and type, including `0`, empty strings, and numeric
strings. Parsing happens before authentication so a valid request's ID can be
included in authentication errors. Bounded parsing does not grant downstream
access; authentication and authorization must both succeed before forwarding.
Duplicate JSON keys are rejected to avoid disagreement about the authorized
tool name between parsers.

Authenticated notifications receive empty HTTP 204 and are never executed or
forwarded; tool operations require request IDs in this subset. Unauthenticated
notifications receive empty HTTP 401 with a bearer challenge. No JSON-RPC reply
is invented for valid notifications. Malformed envelopes are invalid requests,
not valid notifications.

Application logs contain static failure categories only. Credentials, role
maps, exception values, request arguments, and response bodies are never logged.
CLI access logs are disabled. The mock stores received JSON in an in-memory test
spy, with no endpoint exposing it and no disk persistence.

## Transport difference and limitations

Task 1 is an official-SDK MCP server launched as a child process with stdio
JSON-RPC framing, lifecycle negotiation, and stdout isolation. Task 2 is a
standalone HTTP reverse proxy: each `POST /mcp` carries one JSON-RPC request and
returns one JSON-RPC response. It neither spawns nor modifies Task 1. The mock
downstream implements the same limited HTTP/JSON-RPC tool surface.

This is **not a full MCP Streamable HTTP transport implementation**: it has no
initialize/discover forwarding, session IDs, protocol negotiation, SSE, batch
requests, or server-to-client requests. It implements the assessment's two-method
HTTP subset. Task 1's full SDK client should not be pointed at it as if it were
a complete transport endpoint.

Mock tokens have no issuer, expiry, rotation endpoint, or user directory; rotate
configuration and restart to revoke them. TLS termination, production identity,
client request-read deadlines, and deployment-level ingress controls are outside
this local submission. The unauthenticated mock must stay on loopback or a private
network unreachable by agent clients. A direct connection to it intentionally
bypasses gateway policy. Validation is on Windows/Python 3.11.5; direct tested
dependency versions are pinned here, but transitives are not hash-locked.

## Tests and assessment evaluation

```shell
python -m pytest task_02_security/tests -q
python -m pytest -q
```

Tests use randomly generated mock tokens, ASGI-backed downstream spies,
deterministic HTTPX fault injection, and two real Uvicorn subprocess services.
No external APIs or production credentials are needed. See `VALIDATION.md` for
executed counts and a PASS/PARTIAL/FAIL evaluation of each requirement.

Implementation references: [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/),
[HTTPX timeouts](https://www.python-httpx.org/advanced/timeouts/), and
[HTTPX exceptions](https://www.python-httpx.org/exceptions/).
