# Optional fifth component: public-interface CLI adapter

The four `task_*` packages are the primary submissions. This package is optional
and contains no core server, authorization, redaction, limiter, or fallback
implementation. It imports no task implementation. Removing this directory
does not change any task's configuration, interfaces or tests.

Run from the repository root after installing the existing dependencies:

```shell
python -m optional_demo --task 1
python -m optional_demo --task 2
python -m optional_demo --task 3
python -m optional_demo --task 4
python -m optional_demo --all
```

`--task` and `--all` are mutually exclusive. `--all` runs sequentially, starting
only the services needed for the current selection and stopping them before the
next task. Reports are JSON lines constructed from actual public responses.
No hardcoded successful backend response is substituted when something fails.

| Selection | Real public interfaces exercised | Owned mock dependencies |
| --- | --- | --- |
| 1 | Official MCP SDK client -> `python -m task_01_mcp`, stdio tools/list and tools/call | Task 1's built-in customer/refund fixtures |
| 2 | HTTP POST `/mcp`: list, viewer permitted call, viewer denied admin call, admin allowed call | Task 2 `--mock`, never the real Task 1 server |
| 3 | HTTP POST `/v1/generate`: consume actual redacted SSE through `[DONE]` | Task 3 `--mock`, never Task 4 |
| 4 | HTTP POST `/v1/complete`: real primary-429 fallback and above-limit rejection | Task 4's primary/secondary mocks and a private on-disk SQLite database |

The adapter does not interconnect the four tasks into a pipeline. Task 1's stdio
transport is preserved. Task 2's independent fixture supplies its tool catalog;
Task 3's provider supplies its synthetic PII; Task 4's router remains responsible
for its own accounting and fallback. The demo's SSE reader is a consumer of the
gateway output, not a redactor or replacement provider.

All HTTP ports are selected privately on loopback. Credentials are generated per
run, supplied only through child environment variables, and never printed or
saved. Existing task-specific environment variables are removed from the private
child environment before configuring the selected task; the user's shell is
unchanged. Task 4's database lives in a temporary directory and is removed after
its owned services stop. It never uses or resets the evaluator's normal ledger.

Startup failure, invalid/incomplete backend output, missing `[DONE]` or an
unexpected denial exits nonzero. Owned processes are cleaned up on failure and
interrupt; other user processes are never terminated. A backend diagnostic body
is not printed as a success result. There is a small bind-after-port-selection
race; a collision fails visibly rather than hijacking another service.

## Separate verification

```shell
python -m pytest optional_demo/tests -q
python tools/verify_independence.py
python -m pytest -q
```

The optional suite starts actual task subprocesses and calls their public
interfaces. Fault tests cover startup failure, unavailable backends, unfinished
SSE and environment isolation. Architectural checks reject task-core imports in
this adapter and sibling/demo imports in task packages.

The independence verifier makes temporary single-task copies with sibling/demo
imports explicitly blocked. It disables only pytest's disposable cache plugin
in those copies; all tests and warning-as-error checks remain active. Its copied
task suites include their own real CLI/mock subprocess integrations.

The task technical READMEs and validation records remain authoritative. This
short demo does not replace their full tests, run the benchmarks, exercise every
failure mode, broaden supported PII/provider formats, or change token accounting.
See `../docs/independence.md` for executed verification results.
