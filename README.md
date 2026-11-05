# AI infrastructure assessment — four independent deliverables

Tasks 1–4 are the primary engineering submissions. Each owns its implementation,
configuration, mocks, technical README and tests. The optional CLI demo is a
separate fifth component; it is never needed to start, test or review any task.
No task imports another task or the demo. No core implementation was moved.

## Install

Use Python 3.11+ from this directory:

```shell
python -m venv .venv
```

Activate with `.venv\Scripts\Activate.ps1` in PowerShell, or
`source .venv/bin/activate` on POSIX. Then:

```shell
python -m pip install -e ".[dev]" -r task_01_mcp/requirements.txt -r task_02_security/requirements.txt -r task_03_streaming/requirements.txt -r task_04_limiter/requirements.txt
```

This installs the tested direct dependency versions. Transitively resolved
packages are not hash-locked. SQLite comes with Python; no paid API keys are
required. A shared virtual environment/dependency declaration does not imply a
shared runtime, database, identity map or configuration dependency.

## Evaluate each task independently

Run all commands from the repository root. HTTP services default to loopback.
Task-specific READMEs are authoritative for configuration, examples, limitations
and benchmark evidence. Start only the mocks in the selected row.

| Primary deliverable | Independent startup | Its own mock dependencies | Independent tests | Technical README |
| --- | --- | --- | --- | --- |
| 1. Strict MCP server | `python -m task_01_mcp` | Built-in deterministic customer/refund data; no other service | `python -m pytest task_01_mcp/tests -q` | [Task 1](task_01_mcp/README.md) |
| 2. HTTP/JSON-RPC security gateway | `python -m task_02_security` | `python -m task_02_security --mock` | `python -m pytest task_02_security/tests -q` | [Task 2](task_02_security/README.md) |
| 3. Streaming PII gateway | `python -m task_03_streaming` | `python -m task_03_streaming --mock --delay 0.05` | `python -m pytest task_03_streaming/tests -q` | [Task 3](task_03_streaming/README.md) |
| 4. SQLite quota/fallback router | `python -m task_04_limiter` | `python -m task_04_limiter --service primary` and `python -m task_04_limiter --service secondary` | `python -m pytest task_04_limiter/tests -q` | [Task 4](task_04_limiter/README.md) |

Task 1 remains **stdio**, not HTTP. The command waits for an MCP client; stdout
is protocol-only. `python -m task_01_mcp.client_example` independently launches
its own Task 1 subprocess and exercises its official SDK interface.

Task 2 remains a two-method HTTP/JSON-RPC gateway with its own mock downstream,
not the real Task 1 server. Default gateway/mock ports are 8082/8083. Configure
its authenticated mock keys in the Task 2 gateway shell only:

```powershell
$task2Admin = python -c "import secrets; print(secrets.token_urlsafe(32))"
$task2Viewer = python -c "import secrets; print(secrets.token_urlsafe(32))"
$task2Map = @{}
$task2Map[$task2Admin] = 'admin'
$task2Map[$task2Viewer] = 'viewer'
$env:TASK2_TOKEN_ROLES = $task2Map | ConvertTo-Json -Compress
python -m task_02_security
```

Task 3 remains a standalone SSE gateway with its own provider on ports 8084/8085.
It does not route through Task 4. Its bounded pattern coverage and supported
provider event schema are documented in its technical README.

Task 4 uses its own providers on ports 8087/8088 and gateway on 8086. Configure
its key map and on-disk database in the Task 4 gateway shell only:

```powershell
$task4Key = python -c "import secrets; print(secrets.token_urlsafe(32))"
$task4Map = @{}
$task4Map[$task4Key] = 'tenant-a'
$env:TASK4_API_KEYS = $task4Map | ConvertTo-Json -Compress
$env:TASK4_DATABASE = Join-Path $PWD 'data\task4_quota.sqlite3'
python -m task_04_limiter
```

Task 4's quota is 50000 units per rolling 60 seconds under its documented
UTF-8-byte logical-request contract, not native-provider aggregate retry billing.
Tasks do not read each other's `TASK2_*`, `TASK3_*` or `TASK4_*` configuration.
Task 4's ledger is not used by any other task. The original `mock_services/`
fixtures and scaffold `.env.example` are not dependencies of these four tasks.
No automatic `.env` loader or common runtime configuration is required.

## Independence verification and complete repository tests

```shell
python tools/verify_independence.py
python -m pytest -q
```

The verifier creates a temporary checkout containing only one task and the pytest
configuration, blocks imports of all sibling tasks, the optional demo and legacy
shared mocks (including editable-install fallback), and runs that task's own
suite. Its subprocesses use the copied task's own public entry points and mocks.
It leaves the real checkout unchanged. To evaluate one selected task:

```shell
python tools/verify_independence.py --task 3
```

The full pytest suite additionally checks architectural import boundaries and
executes the optional adapter's tests. A failure in the optional adapter never
prevents running the independent commands in the table. See
[verified execution record](docs/independence.md) for actual counts and limits.

## Optional demo launch — fifth component only

```shell
python -m optional_demo --task 1
python -m optional_demo --task 2
python -m optional_demo --task 3
python -m optional_demo --task 4
python -m optional_demo --all
python -m pytest optional_demo/tests -q
```

Choose one command; `--all` runs the four demonstrations sequentially. This is a
CLI adapter/orchestrator, not another application containing their core logic.
It launches the existing task CLIs and their own mocks on private ephemeral
loopback ports, uses fresh private mock credentials, and gives Task 4 a temporary
on-disk ledger. It never modifies the shell's configuration or an existing task
service/database. Task 1 is called through the official SDK stdio client; Tasks
2–4 are called through their public HTTP interfaces.

Reports contain actual backend results. Task 2 demonstrates authorized and denied
calls; Task 3 consumes real sanitized SSE output; Task 4 demonstrates real 429
fallback and a quota rejection. There are no replacement servers or synthetic
successful responses. A backend failure exits nonzero and owned processes are
cleaned up; no credentials or backend diagnostic bodies are printed. A rare port
allocation race fails visibly instead of reusing another service. The optional
adapter is not a substitute for the individual correctness/security tests.

See [optional demo details](optional_demo/README.md). Removing or breaking
`optional_demo/` does not change any task's imports, startup command or tests.
No frontend or shared runtime state was introduced.

## Review evidence and version control

Each task retains `VALIDATION.md`; Tasks 3–4 retain reproducible benchmark scripts,
raw measurements and benchmark explanations. Original `docs/validation.md`,
`docs/decisions.md` and `docs/FILES.md` describe the historical scaffold and are
superseded by current technical READMEs and the independence record.

After each completed assessment change: run relevant tests, review the diff and
staged files for secrets/generated data, commit, attempt a normal push and verify
the remote SHA. Never force-push or overwrite remote work. Report missing tests,
credentials/configuration or a failed push explicitly. A local commit is not a
verified GitHub publication.
