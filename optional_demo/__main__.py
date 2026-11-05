"""Optional adapter; removing this package does not affect any task."""

import argparse
import json
import sys


def main():
    parser = argparse.ArgumentParser(description="Optional public-interface demo; tasks remain primary and independent")
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--task", type=int, choices=[1, 2, 3, 4])
    selection.add_argument("--all", action="store_true")
    args = parser.parse_args()
    from .runner import run

    for task in range(1, 5) if args.all else [args.task]:
        try:
            result = run(task)
            print(json.dumps(result, sort_keys=True), flush=True)
        except KeyboardInterrupt:
            print("Demo interrupted; owned services have been stopped.", file=sys.stderr)
            return 130
        except Exception:
            print(f"Task {task} demo failed; run that task's documented command/tests for diagnostics.", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
