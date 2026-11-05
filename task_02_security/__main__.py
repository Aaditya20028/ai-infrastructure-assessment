"""Setup-only launcher; no task behavior is implemented."""

import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="MCP security gateway: setup-only scaffold")
    parser.parse_args()
    print("Task implementation pending; see this task's README.md.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
