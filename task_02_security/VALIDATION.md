# Task 2 validation and assessment evaluation

Environment: Windows, Python 3.11.5; FastAPI 0.162.0, Uvicorn 0.54.0,
HTTPX 0.28.1, Pydantic 2.14.2, pytest 9.2.0, pytest-asyncio 1.4.1.post1.
Task 1 continues to use MCP/mcp-types 2.3.0.

## Actual test executions

```shell
.venv/Scripts/python -u -m pytest task_02_security/tests -q -o faulthandler_timeout=40
# 97 passed in 7.85 seconds
.venv/Scripts/python -u -m pytest -q -o faulthandler_timeout=40
# 201 passed in 18.80 seconds
```

No skips, expected failures, or warnings were reported. All 96 Task 1 tests
still pass. The two real-network tests start both documented CLI services in
separate subprocesses and exchange actual loopback HTTP requests. Remaining
integration tests use a real FastAPI app and an ASGI downstream spy or HTTPX
fault transport, without paid APIs or production secrets. Tokens are generated
randomly in test fixtures. Timeouts use cancellation of an event waiter, without
sleep-based timing assertions. Network permission was enabled for Windows
asyncio and local socket tests.

| Test file/group | Passed | Coverage |
| --- | ---: | --- |
| `tests/test_auth_policy.py` | 28 | Role matrix, verified tokens, invalid schemes/headers, config validation, fail-closed CLI startup |
| `tests/test_gateway.py` | 39 | Admin/viewer calls, transparent listing, spoofed roles, no-forward spy assertions, exact IDs, malformed input, notifications and size limits |
| `tests/test_failures.py` | 28 | HTTP/network errors, wrong IDs/content types, timeouts, malformed/oversize responses, sanitized errors, cookie and credential isolation |
| `tests/test_http_integration.py` | 2 | Real Uvicorn gateway plus mock, both roles, listing, auth errors and malformed JSON |
| Task 1 existing tests | 96 | Original strict SDK stdio server and clients |
| Other existing regression tests | 8 | Shared HTTP mocks, SQLite probe, tasks 3–4 scaffolds |
| **Total** | **201** | Full repository suite |

## Assessment requirements

| Requirement | Evaluation | Evidence |
| --- | --- | --- |
| 1. HTTP/JSON-RPC reverse proxy between agent and mock MCP server | PASS | Independent gateway and mock CLI services; real HTTP integration tests |
| 2. Read Bearer authorization and extract admin/viewer role | PASS | Constant-time token comparison against configured server-side roles; no unverified role claims |
| 3. Authenticated tools/list forwards transparently | PASS | Original request bytes, ID and metadata reach downstream; original response bytes preserved; admin tool remains visible to viewers |
| 4. Inspect tools/call params.name | PASS | Strict Pydantic ToolCall validates nonempty string name before policy |
| 5. Only admin may execute admin_ prefixed tools | PASS | Admin reset succeeds; viewer reset denied; spoofed header/parameter roles ignored |
| 6. Unauthorized call returns -32001 and exact message | PASS | HTTP 403 JSON-RPC error is exactly Unauthorized Tool Call, with original ID |
| 7. Unauthorized calls never reach downstream | PASS | Explicit assertions on both forwarding transport spy and downstream call list show zero calls |
| 8. Preserve JSON-RPC IDs and response format | PASS | Integer/string/zero/empty-string IDs, transparent response bytes, wrong upstream ID/type rejected |
| 9. Safely handle malformed JSON, bad tokens, failures and timeouts | PASS | Parse/envelope/param errors; 401 challenge; sanitized 502/504; bounded payloads and total timeout; redirects disabled |

## Engineering and deliverables

| Item | Evaluation | Evidence / limit |
| --- | --- | --- |
| Authenticated configurable mock credentials | PASS | Required environment map; random setup/test tokens; configuration errors are sanitized |
| Separate authentication, authorization and forwarding | PASS | auth.py, policy.py, proxy.py; app.py composes them |
| Async forwarding and lifecycle cleanup | PASS | Lifespan-managed AsyncClient; bounded streaming read; response and client closure; deadline cancellation |
| Credentials/sensitive data not logged or forwarded | PASS | Log assertions and transport header assertions; static failure categories; access logs disabled |
| Independently runnable code and mock | PASS | Gateway and --mock CLI startup exercised over real HTTP |
| Task 1 preserved; tasks 3–4 untouched | PASS | Changes scoped to task_02_security; full Task 1 regression passes |
| README, examples, test results and limitations | PASS | README.md, this file, requirements.txt and FILES.md |
| Full MCP Streamable HTTP/session/SSE compatibility | PARTIAL | Only the requested tools/list and tools/call HTTP request-response subset is supported; full transport is outside this assessment task |
| Cross-platform and fully locked environment validation | PARTIAL | Executed on Windows only; direct tested versions pinned, transitives not hash-locked |

Git commit/push status is reported separately in the chat after the actual
attempt and remote verification, so this test record does not claim publication.

## Known limitations

- This is the specified lightweight two-method JSON-RPC HTTP subset, not an SDK
  Streamable HTTP server. No sessions, negotiation, SSE, batches, or server
  requests. Authenticated notifications are ignored without executing tools.
- Bearer credentials are configurable mock shared secrets without token expiry,
  a production identity provider, revocation endpoints, or automatic rotation.
- Local HTTP is for loopback development. Protect the downstream from direct
  client access; configure TLS and ingress controls for any remote deployment.
- Gateway request and downstream response sizes are bounded; production ingress
  client-read deadlines and deployment-level limits remain external concerns.
- The mock has an in-memory spy and no real key reset, credential storage,
  persistence, or external integration. No production security certification or
  tests on other platforms are claimed.
