# Independent evaluation and optional adapter verification

The four task packages are the primary deliverables. The optional fifth
component is a CLI adapter. No file inside any of the four task packages was
changed from baseline commit `d97f1914b92746b48aaac9e435a5cd55994930a2`.
Their implementations, tests, benchmark artifacts and technical READMEs remain
unchanged. Root documentation now describes the completed tasks accurately.

## Executed standalone verification

```shell
.venv/Scripts/python -u tools/verify_independence.py
```

The command completed with exit code 0. For each task it created a temporary
directory containing only that task's source/tests/docs and `pyproject.toml`.
Imports of sibling tasks, `optional_demo` and legacy `mock_services` were
explicitly blocked, including fallback through the editable installation.
`PYTHONPATH` carried that restriction into child processes. Each unchanged
suite launched its own documented CLI/mock integrations from the copy.

| Independent task | Passed | Actual test time |
| --- | ---: | ---: |
| Task 1, official SDK stdio | 96 | 8.18 s |
| Task 2, own HTTP mock downstream | 97 | 4.97 s |
| Task 3, own streaming provider | 57 | 6.12 s |
| Task 4, own providers and disk ledger | 85 | 28.14 s |

These are separate suite counts, not additional tests to add to the full-suite
total. The verifier retains strict configuration and warning-as-error behavior.
It disables only pytest's unnecessary cache plugin in disposable copies: the
initial run hit a Windows sandbox cache-directory rename restriction after test
execution. The corrected command above passed completely. No task code or test
was altered to work around the cache restriction.

Python dependencies are supplied by the existing virtual environment; this is
an application-independence test, not a claim of four isolated dependency builds.
The technical READMEs retain direct pinned dependencies and explicit limitations.

## Executed optional and complete-repository verification

```shell
.venv/Scripts/python -u -m pytest optional_demo/tests -q -o faulthandler_timeout=40
# 7 passed in 14.03 seconds
.venv/Scripts/python -u -m pytest -q -o faulthandler_timeout=40
# 356 passed in 56.37 seconds
```

The optional suite executes `python -m optional_demo --all` against real task
subprocesses. It observes actual Task 1 stdio tool results, Task 2 authorization
responses, Task 3 sanitized SSE completion, and Task 4 real fallback/quota denial.
Separate tests reject missing services and incomplete/error SSE, verify private
configuration, and forbid imports of core task implementations by the adapter.

The full suite contains the unchanged 341 existing tests plus eight task import/
documentation-boundary checks and seven optional adapter tests. No skips,
expected failures or warnings were reported in the passing test runs. Execution
was on Windows with Python 3.11.5 and the already documented dependency versions.
The prior task benchmarks were not rerun or changed for this adapter work.

The editable package install was also refreshed successfully using
`pip install --no-deps --no-build-isolation --no-cache-dir -e .`. On this sandbox,
that required a short writable temporary path under the workspace to avoid
Windows temporary-directory rename and path-length restrictions. Setuptools
emitted its normal editable-install advisory; installation completed successfully.
No new third-party dependency was introduced.

## Architecture requirement checklist

| Requirement | Result | Evidence |
| --- | --- | --- |
| 1. Four separately runnable, testable and reviewable tasks | PASS | All four suites pass in single-task copies with siblings/demo blocked |
| 2. Each retains its own startup, mocks, tests and technical README | PASS | Task directories unchanged; root README command table links to them |
| 3. No merged core application or core moved into demo | PASS | Adapter imports no task implementation and contains only clients/process lifecycle |
| 4. Task 1 remains stdio | PASS | Official SDK subprocess client; original 96 protocol/stdio tests pass |
| 5. Task 2 keeps its own mock, not real Task 1 | PASS | Independent Task 2 CLI --mock; Task 1 imports blocked during its suite |
| 6. Task 3 keeps its provider and does not depend on Task 4 | PASS | Independent Task 3 CLI --mock; Task 4 imports blocked during its suite |
| 7. No shared runtime state or cross-task configuration dependency | PASS | Original per-task env prefixes; adapter config is private per selected task; temporary Task 4 ledger |
| 8. Separate adapter calls existing public interfaces | PASS | CLI entry points, official SDK stdio client and HTTP clients only |
| 9. Owned mocks are real, with no replacement/fake success | PASS | Real --all integration test, no local replacement backend, failed/missing backend tests |
| 10. Demo failure cannot prevent independent task execution | PASS | No task imports optional code; standalone copies omit it entirely; failure tests clean up owned services |

The optional package is not a replacement for individual assessment evaluation.
It is not a frontend or a fifth merged backend. `--all` visits four independent
systems sequentially, not a cross-task pipeline. It does not silently compose
Task 2 authentication, Task 3 filtering and Task 4 routing into a new product.

## Exact change inventory

```text
M README.md
M pyproject.toml
A docs/independence.md
A optional_demo/README.md
A optional_demo/__init__.py
A optional_demo/__main__.py
A optional_demo/processes.py
A optional_demo/runner.py
A optional_demo/tests/test_adapter.py
A tests/test_independence.py
A tools/verify_independence.py
```

Only package discovery, description and full-suite discovery changed in
`pyproject.toml`; task dependencies/configuration were not changed. Runtime
temporary directories, SQLite files, credentials, virtual environments and
caches are not deliverables. Git push status is reported separately after its
actual attempt and independent remote SHA verification.
