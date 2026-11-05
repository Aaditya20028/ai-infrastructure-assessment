import subprocess
import sys


def test_launcher_reports_pending_without_writing_stdout():
    result = subprocess.run(
        [sys.executable, "-m", "task_03_streaming"],
        capture_output=True, text=True, timeout=10, check=False,
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert "implementation pending" in result.stderr
