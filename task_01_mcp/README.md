# MCP server

Status: setup only. No task logic, server routes, authorization, redaction,
limiting, or fallback behavior has been implemented.

From the repository root after installing dependencies:

```shell
python -m task_01_mcp --help
python -m task_01_mcp
python -m pytest task_01_mcp/tests
```

The launcher exits with status 2 and a stderr diagnostic until implementation.
It does not start a server. Each package is independently launchable and has
its own test directory; dependency management is shared at repository root.

Proposed architecture: Official SDK owns framing and stdio. Future tools use explicit strict Pydantic schemas; diagnostics go to stderr.

These are engineering proposals, not additional assessment requirements.
See `../docs/decisions.md` for unresolved acceptance criteria.
