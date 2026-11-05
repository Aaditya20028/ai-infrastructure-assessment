# Streaming PII gateway

Status: setup only. No task logic, server routes, authorization, redaction,
limiting, or fallback behavior has been implemented.

From the repository root after installing dependencies:

```shell
python -m task_03_streaming --help
python -m task_03_streaming
python -m pytest task_03_streaming/tests
```

The launcher exits with status 2 and a stderr diagnostic until implementation.
It does not start a server. Each package is independently launchable and has
its own test directory; dependency management is shared at repository root.

Proposed architecture: FastAPI handles the HTTP boundary and httpx owns upstream streams. Redaction must retain enough state across chunks to avoid releasing partial PII; define the supported PII scope before implementation.

These are engineering proposals, not additional assessment requirements.
See `../docs/decisions.md` for unresolved acceptance criteria.
