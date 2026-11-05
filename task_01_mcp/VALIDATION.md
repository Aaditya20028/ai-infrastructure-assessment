# Task 1 validation record

Validated on Windows with Python 3.11.5, MCP/mcp-types 2.3.0, Pydantic 2.14.2,
pytest 9.2.0, and pytest-asyncio 1.4.1.post1. This record supersedes the original
scaffold's environment limitations for Task 1. The root scaffold documentation
is historical; Task 1 is implemented and tasks 2–4 remain scaffolds.

Final command executed:

```shell
.venv/Scripts/python -u -m pytest -q -o faulthandler_timeout=40
```

**105 passed in 12.58 seconds**, including all 96 Task 1 tests and the nine
existing repository regression tests. No skips or expected failures. The default
pytest configuration treats warnings as errors. Also executed successfully:

```shell
.venv/Scripts/python -m task_01_mcp.client_example
```

The client listed exactly two tools, returned Alex Example, simulated a refund
with receipt `MOCK-1cf53cd5ca677d8e`, and caught protocol error `-32602` for a
zero-amount refund. Tests cover:

- Customer format, strict types, extra/missing arguments, reason boundaries,
  zero/negative/nonfinite amounts, positive JSON numbers, deterministic receipts,
  absent mock customers, and sanitized unexpected errors.
- Actual subprocess `initialize`, `tools/list`, `tools/call`, unknown tools and
  methods, malformed frames and parameters, UTF-8, notification silence,
  integer/string/zero IDs and concurrent outstanding request correlation.
- Bare non-JSON numeric constants vs valid numeric overflow; recovery after bad
  frames; SDK clients in both auto-discovery and legacy handshake modes.
- Python prints, fd writes, inherited child output, handler diagnostics, and
  exit hooks diverted to stderr; every stdout frame is JSON-RPC, with no trailing
  contamination; clean EOF shutdown.

During development, the first raw-wire run found the SDK treating invalid
boolean/fractional request IDs as notifications. Explicit guard validation fixed
both failures before the final run. Earlier sandbox runs hung in Windows
asyncio's local socket-pair creation; the final tests ran successfully after
network permission was granted. No remote API is used by the server or tests.

Not claimed: validation on Linux/macOS, arbitrary SDK versions, a transitive
dependency hash lock, production payment correctness, or production service
authentication. These are deterministic local assessment mocks.
