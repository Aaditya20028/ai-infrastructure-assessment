"""Independently launch Task 4 gateway, primary, or secondary fixture."""

import argparse
import logging
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="SQLite sliding-window LLM router")
    parser.add_argument("--service", choices=["gateway", "primary", "secondary"], default="gateway")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int)
    parser.add_argument("--behavior", choices=["ok", "rate_limit", "slow", "unavailable"], default="ok")
    parser.add_argument("--delay", type=float, default=3.2)
    options = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr, format="%(levelname)s %(message)s", force=True)
    import uvicorn

    try:
        if options.service == "gateway":
            from .app import create_app

            app = create_app()
        else:
            from .mock_provider import create_mock_app

            app = create_mock_app(options.service, options.behavior, options.delay)
        port = options.port if options.port is not None else {"gateway": 8086, "primary": 8087, "secondary": 8088}[options.service]
        uvicorn.run(app, host=options.host, port=port, access_log=False)
    except Exception:
        logging.error("Task 4 could not start; check configuration and database availability")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
