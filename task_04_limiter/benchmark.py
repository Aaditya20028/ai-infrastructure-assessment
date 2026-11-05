"""Actual on-disk quota throughput, atomicity probes and local fallback latency."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import importlib.metadata
import json
from pathlib import Path
import platform
import sqlite3
import statistics
import tempfile
import time

import httpx

from .devtools import local_services, process_probe
from .storage import QuotaStore


def storage_bench(folder, operations):
    store = QuotaStore(folder / "throughput.db")
    started = time.perf_counter()
    for n in range(operations):
        assert store.reserve("throughput", f"request-{n}", 100)
    admission_seconds = time.perf_counter() - started
    started = time.perf_counter()
    for n in range(operations):
        assert store.settle(f"request-{n}", 30)
    settlement_seconds = time.perf_counter() - started
    assert store.usage("throughput") == operations * 30
    path = folder / "threads.db"
    shared = QuotaStore(path, clock=lambda: 100.0)

    def reserve(index):
        return QuotaStore(path, clock=lambda: 100.0).reserve("concurrent", str(index), 1000)

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=8) as pool:
        decisions = list(pool.map(reserve, range(64)))
    thread_seconds = time.perf_counter() - started
    usage = shared.usage("concurrent")
    assert sum(decisions) == 50 and usage == 50000
    return {"sequential": {"requests": operations, "admission_seconds": admission_seconds,
                            "admissions_per_second": operations / admission_seconds,
                            "settlement_seconds": settlement_seconds, "settlements_per_second": operations / settlement_seconds},
            "threads": {"workers": 8, "attempts": 64, "admitted": sum(decisions), "rejected": 64 - sum(decisions),
                        "reserved_usage": usage, "elapsed_seconds_including_connection_setup": thread_seconds},
            "processes": process_probe(folder / "processes.db")}


def fallback_bench(runs):
    report = {}
    for behavior in ("ok", "rate_limit", "slow"):
        with local_services(behavior=behavior, delay=3.2) as services:
            samples = []
            with httpx.Client(timeout=10, trust_env=False) as client:
                count = runs if behavior != "slow" else min(runs, 3)
                for n in range(count + (1 if behavior != "slow" else 0)):
                    started = time.perf_counter()
                    response = client.post(services["url"], json={"prompt": "benchmark", "max_output_tokens": 64},
                                           headers={"Authorization": "Bearer " + services["token"]})
                    elapsed_ms = (time.perf_counter() - started) * 1000
                    response.raise_for_status()
                    payload = response.json()
                    expected = "primary" if behavior == "ok" else "secondary"
                    assert payload["provider"] == expected
                    if behavior == "slow":
                        assert elapsed_ms >= 3000
                    if n > 0 or behavior == "slow":
                        samples.append(elapsed_ms)
            report[behavior] = {"runs_ms": samples, "median_ms": statistics.median(samples),
                                "selected_provider": expected, "fallback_reason": payload["fallback_reason"],
                                "primary_requested_delay_seconds": 3.2 if behavior == "slow" else 0}
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operations", type=int, default=200)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 1 <= args.operations <= 500 or args.runs < 1:
        parser.error("operations must be 1..500 and runs must be positive")
    with tempfile.TemporaryDirectory(prefix="task4-benchmark-") as temp:
        report = {"environment": {"python": platform.python_version(), "platform": platform.platform(), "sqlite": sqlite3.sqlite_version,
                  "dependencies": {name: importlib.metadata.version(name) for name in ("fastapi", "httpx", "uvicorn", "pydantic")}},
                  "method": {"database": "Temporary on-disk SQLite, WAL, synchronous=FULL, busy timeout 5 seconds",
                             "quota": "50000 units / rolling 60 seconds per tenant, including active holds",
                             "latency": "Actual loopback HTTP + SQLite admission/reconciliation, separate gateway and two mock processes",
                             "slow_runs": "At most 3, no discarded slow warmup; 3.2-second mock response versus strict 3-second primary deadline",
                             "limitations": "Local mock/storage measurements, not real model performance; excludes service startup from HTTP latency; process probe includes spawn"},
                  "storage": storage_bench(Path(temp), args.operations), "fallback": fallback_bench(args.runs)}
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
