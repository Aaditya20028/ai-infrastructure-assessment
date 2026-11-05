"""Local service lifecycle shared by tests and reproducible benchmarks only."""

from contextlib import contextmanager
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]


def available_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


class Service:
    def __init__(self, args, env):
        self.ready = threading.Event()
        self.logs = []
        self.closed = False
        self.process = subprocess.Popen([sys.executable, "-m", "task_03_streaming", *args], cwd=ROOT, env=env,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, encoding="utf-8")
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        if not self.ready.wait(timeout=20):
            self.close()
            raise RuntimeError("Local benchmark/test service failed to start")

    def _read(self):
        for line in self.process.stderr:
            self.logs.append(line)
            if "Uvicorn running on" in line:
                self.ready.set()

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.reader.join(timeout=5)
        self.process.stderr.close()


@contextmanager
def local_services(delay=0.01, repeats=2000):
    provider_port = available_port()
    gateway_port = available_port()
    while provider_port == gateway_port:
        gateway_port = available_port()
    env = {key: value for key, value in os.environ.items() if not key.startswith("TASK3_")}
    env.update(PYTHONIOENCODING="utf-8", TASK3_PROVIDER_URL=f"http://127.0.0.1:{provider_port}/v1/generate",
               TASK3_IDLE_TIMEOUT="5", TASK3_TOTAL_TIMEOUT="60")
    provider = Service(["--mock", "--port", str(provider_port), "--delay", str(delay), "--repeats", str(repeats)], env)
    try:
        gateway = Service(["--port", str(gateway_port)], env)
        try:
            yield {"provider": f"http://127.0.0.1:{provider_port}/v1/generate",
                   "gateway": f"http://127.0.0.1:{gateway_port}/v1/generate", "gateway_service": gateway}
        finally:
            gateway.close()
    finally:
        provider.close()
