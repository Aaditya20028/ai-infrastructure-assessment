"""Process-concurrency and local HTTP harnesses for tests/benchmarks only."""

from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
import json
import multiprocessing
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time

from .storage import QuotaStore

_BARRIER = None


def _worker_setup(barrier):
    global _BARRIER
    _BARRIER = barrier


def _process_batch(arguments):
    path, index, attempts, units = arguments
    store = QuotaStore(path, clock=lambda: 100.0)
    _BARRIER.wait(timeout=20)
    accepted = sum(store.reserve("process-tenant", f"worker-{index}-{n}", units) for n in range(attempts))
    return os.getpid(), accepted


def process_probe(path, workers=4, attempts=20, units=1000):
    store = QuotaStore(path, clock=lambda: 100.0)
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(workers)
    started = time.perf_counter()
    with ProcessPoolExecutor(max_workers=workers, mp_context=context, initializer=_worker_setup, initargs=(barrier,)) as pool:
        results = list(pool.map(_process_batch, [(str(path), i, attempts, units) for i in range(workers)]))
    return {"workers_used": len({pid for pid, _ in results}), "attempts": attempts * workers,
            "admitted": sum(count for _, count in results), "usage": store.usage("process-tenant"),
            "elapsed_seconds_including_spawn": time.perf_counter() - started}


def available_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


class Service:
    def __init__(self, args, env):
        self.ready = threading.Event()
        self.logs = []
        self.closed = False
        root = Path(__file__).resolve().parents[1]
        self.process = subprocess.Popen([sys.executable, "-m", "task_04_limiter", *args], cwd=root, env=env,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, encoding="utf-8")
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        if not self.ready.wait(timeout=20):
            self.close()
            raise RuntimeError("Local Task 4 service failed to start")

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
def local_services(behavior="ok", delay=3.2, secondary_behavior="ok"):
    ports = set()
    while len(ports) < 3:
        ports.add(available_port())
    primary_port, secondary_port, gateway_port = sorted(ports)
    token = secrets.token_urlsafe(32)
    env = {key: value for key, value in os.environ.items() if not key.startswith("TASK4_")}
    with tempfile.TemporaryDirectory(prefix="task4-") as folder:
        env.update(PYTHONIOENCODING="utf-8", TASK4_API_KEYS=json.dumps({token: "benchmark-tenant"}),
                   TASK4_DATABASE=str(Path(folder) / "quota.sqlite3"),
                   TASK4_PRIMARY_URL=f"http://127.0.0.1:{primary_port}/v1/complete",
                   TASK4_SECONDARY_URL=f"http://127.0.0.1:{secondary_port}/v1/complete", TASK4_SECONDARY_TIMEOUT="3")
        services = []
        try:
            for args in [
                ["--service", "primary", "--port", str(primary_port), "--behavior", behavior, "--delay", str(delay)],
                ["--service", "secondary", "--port", str(secondary_port), "--behavior", secondary_behavior],
                ["--port", str(gateway_port)],
            ]:
                services.append(Service(args, env))
            yield {"url": f"http://127.0.0.1:{gateway_port}/v1/complete", "token": token,
                   "database": Path(folder) / "quota.sqlite3", "services": services}
        finally:
            for service in reversed(services):
                service.close()
