# Task 1: Strict customer MCP server

Working stdio server with exactly two tools, deterministic in-memory fixtures,
strict Pydantic validation, and protocol-level errors. No API keys, network
downstreams, database, or money movement. Tasks 2–4 remain untouched.

## Install, run, and test

Use Python 3.11+ and run these commands from the repository root. Create and
activate `.venv` as described in the root README, then:

```shell
python -m pip install -e ".[dev]" -r task_01_mcp/requirements.txt
python -m task_01_mcp
```

The server waits for newline-delimited JSON-RPC on stdin. EOF shuts it down.
Do not run it behind Uvicorn or send HTTP requests to it. `--help` writes to
stderr, preserving stdout for protocol messages even during CLI handling.

```shell
python -m pytest task_01_mcp/tests -q
python -m pytest -q
python -m task_01_mcp.client_example
```

The working example starts an actual server subprocess with the official SDK
client, lists both tools, looks up a customer, simulates a refund, and catches
an invalid-refund `MCPError(-32602)`. Its human-readable output belongs to the
separate client process, never the server's protocol pipe.

Direct versions validated here are in `requirements.txt`. They pin the inspected
SDK API but are not a hash-locked transitive environment. Python 3.11.5, MCP and
mcp-types 2.3.0, Pydantic 2.14.2, pytest 9.2.0, and pytest-asyncio 1.4.1.post1
are the tested versions. See `VALIDATION.md` for actual run results.

## Tools and validation

| Tool | Arguments |
| --- | --- |
| `get_customer_record` | `customer_id`: strict string matching `^CUST-[0-9]{5}$` |
| `trigger_refund` | Same ID; `amount`: finite number strictly greater than zero; `reason`: strict string of at least 10 characters |

Argument models forbid extra fields. Strings, booleans, and null are not coerced
to amounts. JSON integer numbers such as `1` are accepted as `1.0` by Pydantic's
strict float type; JSON has no distinct integer/float primitive. IDs use ASCII
digits, with no trimming or case conversion. Reasons are measured by character
count without trimming, matching the stated requirement.

`CUST-00001` is Alex Example; `CUST-00002` is Sam Example. Other well-formed IDs
return `found: false` on lookup and `status: customer_not_found` on refund.
These mock choices are documented behavior, not additional input restrictions.
Valid refunds return `status: simulated`, `mock: true`, and a repeatable receipt
derived from a SHA-256 hash of the normalized request. No state changes, balance
rules, currency rounding, or real payment actions are performed. The receipt is
not an idempotency guarantee for a production payment system.

## Protocol examples

For a handshake-era client, send `initialize`, await its response, then send
`notifications/initialized` before the tool requests. Each object below is a
separate input line; send the next request after reading the previous response.

```json
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"example","version":"1.0"}}}
{"jsonrpc":"2.0","method":"notifications/initialized"}
{"jsonrpc":"2.0","id":"catalog","method":"tools/list","params":{}}
{"jsonrpc":"2.0","id":"lookup","method":"tools/call","params":{"name":"get_customer_record","arguments":{"customer_id":"CUST-00001"}}}
{"jsonrpc":"2.0","id":"refund","method":"tools/call","params":{"name":"trigger_refund","arguments":{"customer_id":"CUST-00001","amount":12.5,"reason":"Product damaged"}}}
{"jsonrpc":"2.0","id":"invalid","method":"tools/call","params":{"name":"trigger_refund","arguments":{"customer_id":"CUST-00001","amount":0,"reason":"Product damaged"}}}
```

The last call produces an error envelope rather than a success result with
`isError: true`:

```json
{"jsonrpc":"2.0","id":"invalid","error":{"code":-32602,"message":"Invalid tool parameters"}}
```

| Failure | JSON-RPC behavior |
| --- | --- |
| Invalid/missing tool arguments; unknown tool | `-32602`, original request ID |
| Malformed outer `params` | `-32602`, original valid request ID |
| Unknown JSON-RPC method | `-32601`, original request ID |
| Unexpected application failure | `-32603`, sanitized message, original request ID |
| Malformed JSON, including literal `NaN`/`Infinity` | `-32700`, null ID |
| Invalid envelope/ID | `-32600`, usable ID if available; otherwise null |
| Valid notification, even with invalid parameters | No response |

NaN and infinities are rejected by Pydantic when supplied as Python values.
Bare `NaN`, `Infinity`, and `-Infinity` are not JSON, so the wire guard rejects
those frames as parse errors. A valid JSON number that overflows a float, such
as `1e999`, reaches finite-number validation and yields `-32602` with its ID.
Results contain JSON text content and matching `structuredContent`.

## SDK inspection and compatibility

Inspected the installed official SDK 2.3.0 source:

- `mcp/server/mcpserver/server.py`, `_handle_call_tool`: high-level tool
  validation exceptions become `CallToolResult(is_error=True)`. That is a tool
  execution result, not the assessment's required JSON-RPC error.
- `mcp/shared/jsonrpc_dispatcher.py`, `handler_exception_to_error_data`:
  `MCPError` preserves its error code and `ValidationError` becomes `-32602`.
  Its legacy catch-all still uses code `0` for arbitrary exceptions.
- `mcp/server/stdio.py`: bad frame validation is yielded as an exception;
  the default dispatcher drops it. The JSON-RPC union can also reinterpret
  an invalid-ID request as a notification by ignoring the ID.

The server therefore uses the official low-level `Server` and
`add_request_handler`, with public middleware to normalize unexpected failures
to `-32603`. Pydantic models generate both the published input schemas and runtime
validation. The narrow transport guard validates malformed frames and serializes
its errors using SDK types; all valid frames go through official `stdio_server`
and SDK lifecycle/dispatch. There is no handwritten replacement MCP dispatcher.

The assessment deliberately uses protocol errors for invalid tool arguments.
Some newer MCP guidance treats input validation as tool execution errors, so
this is an explicit assessment compatibility choice. Unknown tools use `-32602`
because the tool name is a parameter of the existing `tools/call` method; an
unknown JSON-RPC method uses `-32601`.
See the [official SDK](https://github.com/modelcontextprotocol/python-sdk) and
[MCP tool error guidance](https://modelcontextprotocol.io/specification/2025-11-25/server/tools#error-handling).

SDK tests exercise both its modern automatic discovery client and its legacy
handshake client over actual stdio subprocesses. Raw-wire tests negotiate
2025-11-25 and assert exact JSON-RPC envelopes and request-ID types. Re-run tests
when upgrading the SDK; the inspected API and limitations are version-specific.

## Stdout and diagnostics

The module entry point duplicates stdout into a private non-inheritable protocol
pipe before importing dependencies. It diverts fd 1 and Python stdout to stderr,
including the Windows inherited standard handle. The explicit protocol writer
serializes SDK and framing-error writes under one lock. Input is decoded as JSON
UTF-8, independent of the Windows console codepage. Stdout stays diverted through
shutdown and exit hooks; `serve()` should be launched through this entry point.

Logs use stderr and omit rejected values, exception messages, customer IDs, and
refund reasons. Tests inject Python/native/child/exit-hook noise and unexpected
failures in a test-only subprocess; no diagnostic or fault-injection endpoint is
exposed by the production module. Every observed stdout line must be a JSON-RPC
response, and shutdown must leave no unsolicited output.
