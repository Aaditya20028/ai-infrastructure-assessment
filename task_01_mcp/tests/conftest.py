"""Real process harness with bounded reads and continuous stderr draining."""

import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading

import pytest

ROOT = Path(__file__).resolve().parents[2]


class StdioPeer:
    def __init__(self, command=None):
        self.process = subprocess.Popen(
            command or [sys.executable, "-m", "task_01_mcp"], cwd=ROOT,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"},
        )
        self.lines = queue.Queue()
        self.stderr = []
        self.stdout_thread = threading.Thread(target=self._read_stdout, daemon=True)
        self.stderr_thread = threading.Thread(target=self._read_stderr, daemon=True)
        self.stdout_thread.start()
        self.stderr_thread.start()
        self.counter = 0

    def _read_stdout(self):
        for line in self.process.stdout:
            self.lines.put(line)

    def _read_stderr(self):
        self.stderr.extend(self.process.stderr)

    def send_raw(self, text):
        self.process.stdin.write(text + "\n")
        self.process.stdin.flush()

    def send(self, message):
        self.send_raw(json.dumps(message, allow_nan=False))

    def receive(self):
        try:
            line = self.lines.get(timeout=15)
        except queue.Empty:
            pytest.fail("No protocol response; stderr: " + "".join(self.stderr))
        response = json.loads(line)  # Any stdout logging makes this fail.
        assert response["jsonrpc"] == "2.0"
        assert ("result" in response) != ("error" in response)
        return response

    def request(self, method, params=None, request_id=None):
        self.counter += 1
        request_id = self.counter if request_id is None else request_id
        message = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            message["params"] = params
        self.send(message)
        response = self.receive()
        assert response["id"] == request_id
        assert type(response["id"]) is type(request_id)
        return response

    def initialize(self):
        response = self.request("initialize", {
            "protocolVersion": "2025-11-25", "capabilities": {},
            "clientInfo": {"name": "assessment-tests", "version": "1.0"},
        })
        assert "result" in response, response
        assert response["result"]["protocolVersion"] == "2025-11-25"
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def close(self):
        try:
            self.process.stdin.close()
            self.process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
            pytest.fail("Server did not shut down on EOF")
        finally:
            self.stdout_thread.join(timeout=5)
            self.stderr_thread.join(timeout=5)
            self.process.stdout.close()
            self.process.stderr.close()
        assert self.process.returncode == 0, "".join(self.stderr)
        assert self.lines.empty(), "Unsolicited/non-protocol stdout output"


@pytest.fixture(scope="module")
def peer():
    instance = StdioPeer()
    try:
        instance.initialize()
        yield instance
    finally:
        instance.close()
