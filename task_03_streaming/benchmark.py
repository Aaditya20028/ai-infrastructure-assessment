"""Actual loopback latency + isolated streaming-pipeline tracemalloc measurements."""

import argparse
import gc
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import statistics
import time
import tracemalloc

import httpx

from .devtools import local_services
from .models import DeltaEvent
from .redaction import Redactor
from .sse import SSEParser, delta_frame


def latency_run(client, url, prompt):
    parser = SSEParser()
    started = time.perf_counter()
    first = None
    timestamps = []
    completed = False
    with client.stream("POST", url, json={"prompt": prompt}) as response:
        response.raise_for_status()
        headers_ms = (time.perf_counter() - started) * 1000
        for chunk in response.iter_bytes():
            for event in parser.feed(chunk):
                if event.event != "message":
                    raise RuntimeError("Benchmark stream failed")
                if event.data == "[DONE]":
                    completed = True
                    continue
                content = DeltaEvent.model_validate_json(event.data).choices[0].delta.content
                if content:
                    now = time.perf_counter()
                    first = now if first is None else first
                    timestamps.append(now)
        parser.finish()
    if not completed or first is None:
        raise RuntimeError("Benchmark did not observe output and completion")
    return {"headers_ms": headers_ms, "first_output_ms": (first - started) * 1000,
            "total_ms": (time.perf_counter() - started) * 1000, "output_events": len(timestamps),
            "max_inter_output_gap_ms": max(((b - a) * 1000 for a, b in zip(timestamps, timestamps[1:])), default=0)}


def memory_run(target_chars):
    # Reuse fixed input: do not allocate the entire generation or retain output.
    block = "Normal words, order 1234. " * 8
    frame = delta_frame(block)
    repeats = max(1, target_chars // len(block))
    gc.collect()
    tracemalloc.start()
    started = time.perf_counter()
    parser = SSEParser()
    redactor = Redactor()
    digest = hashlib.sha256()
    emitted = 0
    for _ in range(repeats):
        for event in parser.feed(frame):
            content = DeltaEvent.model_validate_json(event.data).choices[0].delta.content
            safe = redactor.feed(content)
            emitted += len(safe)
            digest.update(safe.encode())
    tail = redactor.finish()
    emitted += len(tail)
    digest.update(tail.encode())
    parser.finish()
    current, peak = tracemalloc.get_traced_memory()
    elapsed = time.perf_counter() - started
    tracemalloc.stop()
    assert emitted == repeats * len(block)
    return {"source_chars": repeats * len(block), "wire_bytes": repeats * len(frame), "safe_output_chars": emitted,
            "tracemalloc_current_bytes": current, "tracemalloc_peak_bytes": peak,
            "max_redactor_pending_chars": redactor.max_pending, "max_sse_pending_chars": parser.max_pending,
            "elapsed_seconds": elapsed, "output_sha256": digest.hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--delay", type=float, default=0.05)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be positive")
    report = {"environment": {"python": platform.python_version(), "platform": platform.platform(),
              "dependencies": {name: importlib.metadata.version(name) for name in ("fastapi", "httpx", "uvicorn", "pydantic")}},
              "method": {"runs": args.runs, "provider_delay_seconds_per_delta": args.delay, "warmups_per_case": 1,
                         "monotonic_clock_resolution_seconds": time.get_clock_info("monotonic").resolution,
                         "timer_note": "Requested mock delays are subject to OS scheduling; 50 ms avoids sub-clock-resolution Windows timers",
                         "latency": "Actual loopback HTTP, first nonempty content delta; headers alone do not count",
                         "memory": "In-process SSE parser + delta validation + redactor with discard/hash sink; excludes HTTP/OS buffers and process RSS"},
              "latency": {}}
    with local_services(delay=args.delay) as pair:
        with httpx.Client(timeout=15, trust_env=False) as client:
            for label, endpoint, prompt in [("provider_normal", "provider", "normal"), ("gateway_normal", "gateway", "normal"), ("gateway_pii", "gateway", "demo")]:
                latency_run(client, pair[endpoint], prompt)
                runs = [latency_run(client, pair[endpoint], prompt) for _ in range(args.runs)]
                report["latency"][label] = {"runs": runs, "median": {key: statistics.median(run[key] for run in runs)
                                                        for key in ("headers_ms", "first_output_ms", "total_ms", "max_inter_output_gap_ms")}}
    memory_run(1024)  # Warm model/parser caches before measuring both workloads.
    report["memory"] = [memory_run(size) for size in (131072, 2097152)]
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
