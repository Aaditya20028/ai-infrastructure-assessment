# Pending assessment decisions

Only the four task descriptions in the request are requirements. No tool
catalog, role matrix, PII taxonomy, provider API, or budget policy was supplied.
The following must be clarified before implementing behavior, rather than
quietly choosing an invented assessment specification.

| Task | Acceptance criteria still needed |
| --- | --- |
| MCP | Tools, input/output schemas, limits, error behavior, expected clients/protocol revisions |
| Security | Gateway transport, identity/authentication mechanism, roles and tool matrix, discovery filtering, trust boundary |
| Streaming | Upstream/downstream API shape, input vs output redaction scope, PII categories, replacement semantics, supported encodings and buffering/latency limits |
| Limiter | Identity key, token counting method, quota/window rules, reservation and reconciliation policy, retry/fallback conditions and provider contracts |

## Proposed verification plan, not implemented tests

- MCP: real SDK subprocess round trips; schema failures including extra fields
  and coercion; stdout purity; cancellation and shutdown.
- Security: missing/invalid identity; every role-tool pair; discovery and direct
  invocation bypass attempts; upstream failures and denied calls never forwarded.
- Streaming: PII split at every boundary; UTF-8 and SSE framing; cancellation,
  backpressure, bounded buffering, completion flushing and upstream errors.
  Define what the selected PII detector can guarantee before sending any output.
- Limiter: separate SQLite connections/processes, atomic concurrent reservations,
  persistence after restart, window boundaries, cancellation and reconciliation,
  fallback after different failure modes and no double charging. Use temporary
  disk databases and an injectable clock; avoid sleep-based timing assertions.

Future gateways should use explicit downstream allowlists, bounded request sizes
and timeouts, and sanitized diagnostics. Do not trust caller-supplied roles.
Do not log credentials, prompts or unredacted PII. Determine retry safety before
replaying calls, especially once any streaming output has reached the client.
These are review considerations, not implemented guarantees.
