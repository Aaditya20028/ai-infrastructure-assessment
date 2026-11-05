"""Start/stop only the owned task CLI processes on private loopback ports."""

import os
from pathlib import Path
import socket
import subprocess
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]


class DemoFailure(RuntimeError):
    pass


def child_environment():
    # Never alter the user's shell or let one task's settings configure another.
    env = {key: value for key, value in os.environ.items() if not key.startswith(("TASK2_", "TASK3_", "TASK4_"))}
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def available_ports(count):
    # Keep listeners open until every distinct port has been selected.
    sockets = []
    try:
        for _ in range(count):
            listener = socket.socket()
            sockets.append(listener)
            listener.bind(("127.0.0.1", 0))
        return [listener.getsockname()[1] for listener in sockets]
    finally:
        for listener in sockets:
            listener.close()


class Service:
    def __init__(self, module, args, env, startup_timeout=20):
        self.ready = False
        self.closed = False
        self.started_or_exited = threading.Event()
        self.process = subprocess.Popen([sys.executable, "-m", module, *args], cwd=ROOT, env=env,
                                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.PIPE, text=True, encoding="utf-8")
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        if not self.started_or_exited.wait(timeout=startup_timeout) or not self.ready or self.process.poll() is not None:
            self.close()
            raise DemoFailure("Selected service did not start")

    def _read(self):
        # Drain output to avoid pipe deadlock, but never print/store credentials
        # or a backend's arbitrary diagnostic body in a demo success report.
        for line in self.process.stderr:
            if "Uvicorn running on" in line:
                self.ready = True
                self.started_or_exited.set()
        self.started_or_exited.set()

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

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
