"""Exercise both documented CLI services over actual loopback HTTP sockets."""

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading

import httpx
import pytest

from .conftest import bearer, rpc

ROOT = Path(__file__).resolve().parents[2]


def available_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


class Service:
    def __init__(self, args, env):
        self.ready = threading.Event()
        self.log = []
        self.process = subprocess.Popen([sys.executable, "-m", "task_02_security", *args], cwd=ROOT, env=env,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, encoding="utf-8")
        self.thread = threading.Thread(target=self._logs, daemon=True)
        self.thread.start()
        if not self.ready.wait(timeout=20):
            self.close()
            pytest.fail("HTTP service did not start: " + "".join(self.log))

    def _logs(self):
        for line in self.process.stderr:
            self.log.append(line)
            if "Uvicorn running on" in line:
                self.ready.set()

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.thread.join(timeout=5)
        self.process.stderr.close()


@pytest.fixture(scope="module")
def live_services(tokens):
    mock_port = available_port()
    gateway_port = available_port()
    while gateway_port == mock_port:
        gateway_port = available_port()
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "TASK2_TOKEN_ROLES": json.dumps({token: role for role, token in tokens.items()}),
           "TASK2_UPSTREAM_URL": f"http://127.0.0.1:{mock_port}/mcp", "TASK2_TIMEOUT_SECONDS": "2"}
    # Do not inherit unrelated custom limits from a developer's shell.
    env.pop("TASK2_MAX_REQUEST_BYTES", None)
    env.pop("TASK2_MAX_RESPONSE_BYTES", None)
    mock = Service(["--mock", "--port", str(mock_port)], env)
    try:
        gateway = Service(["--port", str(gateway_port)], env)
        try:
            yield f"http://127.0.0.1:{gateway_port}", gateway
        finally:
            gateway.close()
    finally:
        mock.close()


def test_end_to_end_http_role_enforcement_and_listing(live_services, tokens):
    url, _ = live_services
    with httpx.Client(base_url=url, timeout=10, trust_env=False) as client:
        response = client.post("/mcp", json=rpc(name="admin_reset_key", request_id="admin"), headers=bearer(tokens["admin"]))
        assert response.status_code == 200 and response.json()["id"] == "admin"
        assert json.loads(response.json()["result"]["content"][0]["text"])["key_reset"] is True
        response = client.post("/mcp", json=rpc(name="admin_reset_key", request_id="viewer"), headers=bearer(tokens["viewer"]))
        assert response.status_code == 403 and response.json()["error"]["code"] == -32001
        response = client.post("/mcp", json=rpc(), headers=bearer(tokens["viewer"]))
        assert response.status_code == 200
        response = client.post("/mcp", json=rpc(method="tools/list"), headers=bearer(tokens["viewer"]))
        assert {tool["name"] for tool in response.json()["result"]["tools"]} == {"get_status", "admin_reset_key"}


def test_end_to_end_bad_auth_and_json(live_services, tokens):
    url, service = live_services
    with httpx.Client(base_url=url, timeout=10, trust_env=False) as client:
        response = client.post("/mcp", json=rpc())
        assert response.status_code == 401 and response.json()["error"]["code"] == -32000
        response = client.post("/mcp", content=b"bad-json", headers=bearer(tokens["viewer"]))
        assert response.status_code == 400 and response.json()["error"]["code"] == -32700
    assert all(token not in "".join(service.log) for token in tokens.values())
