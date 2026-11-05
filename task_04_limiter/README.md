# Token limiter and fallback

Status: setup only. No task logic, server routes, authorization, redaction,
limiting, or fallback behavior has been implemented.

From the repository root after installing dependencies:

```shell
python -m task_04_limiter --help
python -m task_04_limiter
python -m pytest task_04_limiter/tests
```

The launcher exits with status 2 and a stderr diagnostic until implementation.
It does not start a server. Each package is independently launchable and has
its own test directory; dependency management is shared at repository root.

Proposed architecture: Use on-disk sqlite3 with atomic budget reservations and reconciliation. httpx provider adapters handle bounded timeouts; fallback and accounting policy must be defined before implementation.

These are engineering proposals, not additional assessment requirements.
See `../docs/decisions.md` for unresolved acceptance criteria.
