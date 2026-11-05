# MCP security gateway

Status: setup only. No task logic, server routes, authorization, redaction,
limiting, or fallback behavior has been implemented.

From the repository root after installing dependencies:

```shell
python -m task_02_security --help
python -m task_02_security
python -m pytest task_02_security/tests
```

The launcher exits with status 2 and a stderr diagnostic until implementation.
It does not start a server. Each package is independently launchable and has
its own test directory; dependency management is shared at repository root.

Proposed architecture: Use SDK clients and servers at protocol boundaries. Authenticate identities before applying deny-by-default tool authorization to both discovery and invocation.

These are engineering proposals, not additional assessment requirements.
See `../docs/decisions.md` for unresolved acceptance criteria.
