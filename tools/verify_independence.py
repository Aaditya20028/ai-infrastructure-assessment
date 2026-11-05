"""Execute each unchanged task's suite with sibling/demo packages unavailable."""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
TASKS = {1: "task_01_mcp", 2: "task_02_security", 3: "task_03_streaming", 4: "task_04_limiter"}


def verify(number):
    task = TASKS[number]
    forbidden = [name for name in TASKS.values() if name != task] + ["optional_demo", "mock_services"]
    # The editable installation might expose the original checkout. Block those
    # imports explicitly as well as omitting their directories from the copy.
    blocker = f'''
import importlib.abc
import sys
class BlockOtherDeliverables(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {forbidden!r}:
            raise ModuleNotFoundError("Unavailable in independent evaluation")
        return None
sys.meta_path.insert(0, BlockOtherDeliverables())
'''
    with tempfile.TemporaryDirectory(prefix=f"independent-task{number}-") as folder:
        isolated = Path(folder)
        shutil.copytree(ROOT / task, isolated / task,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache", ".venv", "*.db", "*.sqlite*"))
        shutil.copy2(ROOT / "pyproject.toml", isolated / "pyproject.toml")
        (isolated / "sitecustomize.py").write_text(blocker, encoding="utf-8")
        env = {key: value for key, value in os.environ.items() if not key.startswith(("TASK2_", "TASK3_", "TASK4_"))}
        env.update(PYTHONPATH=str(isolated), PYTHONIOENCODING="utf-8")
        # Disposable checkout: no pytest cache is needed. Disabling only this
        # plugin also avoids Windows sandbox directory-rename restrictions.
        command = [sys.executable, "-m", "pytest", f"{task}/tests", "-q", "-p", "no:cacheprovider", "-o", "faulthandler_timeout=40"]
        print(f"Task {number}: only {task} copied; sibling/demo imports blocked", flush=True)
        try:
            return subprocess.run(command, cwd=isolated, env=env, timeout=180).returncode
        except subprocess.TimeoutExpired:
            print(f"Task {number}: independent verification exceeded 180 seconds", file=sys.stderr)
            return 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", type=int, choices=[1, 2, 3, 4])
    args = parser.parse_args()
    results = [verify(number) for number in ([args.task] if args.task else range(1, 5))]
    return 0 if all(result == 0 for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
