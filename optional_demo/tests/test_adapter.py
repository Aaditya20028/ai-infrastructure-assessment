import ast
import json
from pathlib import Path
import subprocess
import sys

import httpx
import pytest

from optional_demo.processes import DemoFailure, Service, child_environment
from optional_demo.runner import consume_sse, task_two

ROOT = Path(__file__).resolve().parents[2]


def test_adapter_does_not_import_core_implementations():
    for path in (ROOT / "optional_demo").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                assert not any(alias.name.startswith("task_") for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                assert not node.module.startswith("task_")


def test_child_configuration_is_private_and_does_not_mutate_shell(monkeypatch):
    monkeypatch.setenv("TASK2_TOKEN_ROLES", "private")
    monkeypatch.setenv("TASK4_API_KEYS", "private")
    import os

    before = dict(os.environ)
    child = child_environment()
    assert not any(key.startswith(("TASK2_", "TASK3_", "TASK4_")) for key in child)
    assert dict(os.environ) == before


def test_failed_service_start_is_not_reported_as_success():
    with pytest.raises(DemoFailure):
        Service("module_that_does_not_exist_for_demo", [], child_environment(), startup_timeout=3)


@pytest.mark.parametrize("wire", [b'data: {"choices":[{"delta":{"content":"unfinished"}}]}\n\n', b'event: error\ndata: {}\n\n'])
def test_sse_client_rejects_failed_or_unfinished_backend(wire):
    response = httpx.Response(200, content=wire)
    with pytest.raises(DemoFailure):
        consume_sse(response)


def test_missing_backend_never_produces_fake_success(monkeypatch):
    class MissingService:
        def __init__(self, *args, **kwargs):
            raise DemoFailure("Unavailable")

    monkeypatch.setattr("optional_demo.runner.Service", MissingService)
    with pytest.raises(DemoFailure):
        task_two()


def test_all_four_demos_use_real_public_interfaces():
    result = subprocess.run([sys.executable, "-m", "optional_demo", "--all"], cwd=ROOT,
                            capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert result.returncode == 0, result.stderr
    rows = [json.loads(line) for line in result.stdout.splitlines()]
    assert [row["task"] for row in rows] == [1, 2, 3, 4]
    assert rows[0]["transport"] == "stdio" and rows[0]["customer"]["found"] is True
    assert rows[1]["viewer_admin_denial"]["error"]["code"] == -32001
    assert rows[2]["text"].count("[REDACTED]") == 3
    assert "alice@" not in result.stdout
    assert rows[3]["completion"]["provider"] == "secondary"
    assert rows[3]["quota_denial"]["error"]["code"] == "quota_exceeded"
