# AI infrastructure assessment

## Version control workflow

After each completed assessment task: finish implementation, run available tests
and report blocked checks, review the diff and staged files for secrets, commit
with a descriptive message, push to the configured GitHub remote, and verify
the remote branch SHA. Report the exact changed files, test results, branch and
commit SHA. Never force-push, overwrite remote work, or commit secrets. A commit
is local until Git confirms a successful push; report missing configuration or
authentication explicitly.

**Setup only. The four engineering tasks are intentionally unimplemented.**
The task launchers execute, support `--help`, and otherwise exit 2 with a pending
message on stderr. They do not serve traffic. Mock services are executable fixture
code, not task solutions. No paid keys or production credentials are needed.

## Layout and architecture

| Folder | Proposed responsibility |
| --- | --- |
| `task_01_mcp/` | Official MCP SDK stdio server with strict tool validation |
| `task_02_security/` | MCP gateway with identity-based, deny-by-default tool authorization |
| `task_03_streaming/` | FastAPI streaming gateway with stateful PII redaction |
| `task_04_limiter/` | SQLite token accounting and explicit provider fallback |
| `mock_services/` | Independent stdio MCP and HTTP/SSE downstream fixtures |
| `tests/` | Mock and on-disk SQLite environment checks |
| `docs/decisions.md` | Unknown requirements and proposed future test coverage |

Keep task behavior inside its package. Use SDK transport handling rather than
handwritten MCP framing, Pydantic at trust boundaries, httpx for HTTP calls, and
the standard-library sqlite3 driver for disk storage. Avoid a shared framework
until actual duplication warrants extracting a helper. The official SDK is the
PyPI `mcp` distribution, not the separate `fastmcp` package. This scaffold targets
the SDK 2.x API described in the [official documentation](https://py.sdk.modelcontextprotocol.io/).

## Install

Use a working Python 3.11+ interpreter. The examples assume `python` points to it.
All commands run from this directory. On Windows, `py -3.11` can replace `python`
when that interpreter is installed.

```shell
python --version
python -m venv .venv
```

Activate in PowerShell with `.venv\Scripts\Activate.ps1`, or on POSIX with
`source .venv/bin/activate`. Activation is optional if you invoke the venv's
Python executable directly.

```shell
python -m pip install -e ".[dev]"
python -m pytest
```

`pyproject.toml` is the single dependency declaration. SQLite is included with
Python; do not install a third-party `sqlite3` package. `.env.example` documents
proposed local settings only; no automatic `.env` loader or task settings parser
has been added. The mocks need no environment variables.

## Reproducibility status

Python's minimum version and dependency major-version bounds are declared.
**A resolved dependency lock has not been generated or verified.** Installing
from the pyproject currently resolves available versions and is not an exact
reproduction. Before calling this a reproducible submission, generate and review
a hash-checked lock on a network-enabled machine with Python 3.11+:

```shell
python -m pip install uv==0.6.14
uv pip compile pyproject.toml --extra dev --generate-hashes -o requirements.lock
python -m pip install --require-hashes -r requirements.lock
python -m pip install --no-deps --no-build-isolation -e .
python -m pytest
```

Commit the reviewed `requirements.lock`; subsequent clean installs use the last
three commands, not a fresh resolution. The dev dependencies include the pinned
setuptools used by the editable build. Record the exact interpreter patch
version and platform with the lock.
The pinned uv version above is only a resolver bootstrap, not an assertion that
the dependencies have been resolved here.

## Run the task scaffolds independently

```shell
python -m task_01_mcp --help
python -m task_02_security --help
python -m task_03_streaming --help
python -m task_04_limiter --help
```

Omit `--help` to observe the pending diagnostic and exit status 2. Per-task
README files include isolated test commands. The requested independently serving
implementations belong to the next phase, after acceptance criteria are supplied.

## Run local downstream fixtures

```shell
python -m uvicorn mock_services.http:app --host 127.0.0.1 --port 8090
```

The mock API exposes `GET /health`, `GET /stream`, and
`POST /providers/{primary|secondary}/complete`. POST `{}` returns deterministic
text and fixed fixture usage, while `{"scenario":"unavailable"}` returns 503.
The usage values are fixture data, not tokenizer estimates. `/stream` emits SSE
with a synthetic email split across events, followed by `[DONE]`. It intentionally
contains unredacted fixture PII. This interface makes no vendor compatibility claim.
The mocks do not forward requests, store prompts, or read credentials. Bind only
to loopback; they are unauthenticated development services.

An MCP host can launch the separate stdio fixture using this command from the
repository root (use absolute venv executable and working-directory paths in
host configuration):

```shell
python -m mock_services.mcp_stdio
```

It exposes only `fixture_ping`, returning `pong`, using SDK stdio transport.
It waits for an MCP client; it is not an interactive terminal application.

## Validation status

The setup environment has Python 3.10.10 only; its Python 3.12 launcher is broken.
Package installation failed because the package index was unreachable. Therefore
pytest, dependency resolution, and mock runtime/protocol integration have **not**
been verified here. Syntax and dependency-free launcher checks are recorded in
`docs/validation.md`. Scaffold tests do not establish task correctness or security.
