"""Run the independent Task 3 gateway or mock provider."""

import argparse
import logging
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="Streaming PII SSE gateway")
    parser.add_argument("--mock", action="store_true")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int)
    parser.add_argument("--delay", type=float, default=0.01, help="Mock seconds per generated delta")
    parser.add_argument("--repeats", type=int, default=2000, help="Mock large-fixture repetitions")
    options = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr, format="%(levelname)s %(message)s", force=True)
    import uvicorn

    try:
        if options.mock:
            from .mock_provider import create_mock_app

            app = create_mock_app(delay=options.delay, repeats=options.repeats)
        else:
            from .app import create_app

            app = create_app()
        port = options.port if options.port is not None else (8085 if options.mock else 8084)
        uvicorn.run(app, host=options.host, port=port, access_log=False)
    except Exception:
        logging.error("Task 3 could not start; check configuration")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
