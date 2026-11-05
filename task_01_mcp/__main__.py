"""Reserve the protocol pipe before importing any third-party code."""

import os
import sys


def isolate_stdout():
    wire = os.fdopen(os.dup(sys.stdout.fileno()), "w", encoding="utf-8", newline="\n")
    os.dup2(sys.stderr.fileno(), 1)
    sys.stdout = sys.stderr
    if sys.platform == "win32":
        import ctypes
        import msvcrt

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.SetStdHandle.argtypes = [ctypes.c_ulong, ctypes.c_void_p]
        kernel32.SetStdHandle.restype = ctypes.c_int
        if not kernel32.SetStdHandle(-11 & 0xFFFFFFFF, msvcrt.get_osfhandle(1)):
            wire.close()
            raise OSError("Unable to isolate Windows stdout")
    return wire


def main() -> int:
    with isolate_stdout() as wire:
        import argparse
        import asyncio
        import logging

        parser = argparse.ArgumentParser(description="Strict customer/refund MCP stdio server")
        parser.parse_args()
        logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(message)s", force=True)
        from .server import serve

        try:
            asyncio.run(serve(wire))
        except KeyboardInterrupt:
            return 0
        except Exception as exc:
            logging.error("Server terminated unexpectedly (%s)", type(exc).__name__)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
