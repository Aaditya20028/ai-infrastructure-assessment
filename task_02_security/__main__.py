"""Run the gateway or its independent local mock downstream."""

import argparse
import logging
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="HTTP/JSON-RPC MCP security gateway")
    parser.add_argument("--mock", action="store_true", help="Run the independent mock downstream")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, help="Gateway defaults to 8082; mock defaults to 8083")
    options = parser.parse_args()
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(message)s", force=True)
    import uvicorn

    try:
        if options.mock:
            from .mock_downstream import create_mock_app

            app = create_mock_app()
        else:
            from .app import create_app

            app = create_app()
        uvicorn.run(app, host=options.host, port=options.port or (8083 if options.mock else 8082), access_log=False)
    except Exception:
        # Configuration/exception values can contain credentials.
        logging.error("Task 2 could not start; check configuration and listener settings")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
