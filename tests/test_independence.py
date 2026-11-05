import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TASKS = ["task_01_mcp", "task_02_security", "task_03_streaming", "task_04_limiter"]


@pytest.mark.parametrize("task", TASKS)
def test_task_has_no_sibling_or_demo_import_dependency(task):
    forbidden = set(TASKS) - {task} | {"optional_demo", "mock_services"}
    for source in (ROOT / task).rglob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            assert all(name.split(".")[0] not in forbidden for name in names), str(source)


@pytest.mark.parametrize("task", TASKS)
def test_each_task_retains_documented_independent_commands(task):
    readme = (ROOT / task / "README.md").read_text(encoding="utf-8")
    assert f"python -m {task}" in readme
    assert f"python -m pytest {task}/tests" in readme
    assert (ROOT / task / "__main__.py").is_file()
