# Tokenizer correction: exact change inventory

This correction replaces byte accounting with real cl100k_base token IDs.
Tasks 1–3 remain unchanged. The optional adapter changes only its public
above-quota request and assertion; no core logic moved into it. The earlier
Task 4 creation inventory is preserved in commit d97f1914b92746b48aaac9e435a5cd55994930a2.

```text
M README.md
M docs/independence.md
M optional_demo/runner.py
M optional_demo/tests/test_adapter.py
M pyproject.toml
M task_04_limiter/BENCHMARKS.md
M task_04_limiter/FILES.md
M task_04_limiter/README.md
M task_04_limiter/VALIDATION.md
M task_04_limiter/accounting.py
M task_04_limiter/app.py
M task_04_limiter/benchmark.py
M task_04_limiter/benchmark_results.json
M task_04_limiter/mock_provider.py
M task_04_limiter/requirements.txt
M task_04_limiter/storage.py
M task_04_limiter/tests/conftest.py
M task_04_limiter/tests/test_contract.py
M task_04_limiter/tests/test_gateway.py
A task_04_limiter/tests/test_mock_tokens.py
M task_04_limiter/tests/test_storage.py
A task_04_limiter/tokenization.py
```

The raw benchmark JSON is an intentional deliverable. No tokenizer cache,
SQLite database, API key, environment file, virtual environment or test cache
is committed.
