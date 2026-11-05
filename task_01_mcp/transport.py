"""Guard invalid frames that SDK 2.3 stdio otherwise silently drops.

Only invalid frames are answered here. All valid frames go to the official SDK.
"""

import json
import logging
from typing import TextIO

import anyio
from mcp_types import (
    INVALID_PARAMS, INVALID_REQUEST, PARSE_ERROR, ErrorData, JSONRPCError,
    jsonrpc_message_adapter,
)
from pydantic import ValidationError

logger = logging.getLogger(__name__)


class ProtocolOutput:
    def __init__(self, wire: TextIO):
        self.wire = wire
        self.lock = anyio.Lock()

    async def write(self, text: str) -> None:
        async with self.lock:
            await anyio.to_thread.run_sync(self._write, text)

    def _write(self, text: str) -> None:
        self.wire.write(text)
        self.wire.flush()

    async def flush(self) -> None:
        pass  # Writes already flush under the same lock.

    async def error(self, request_id: int | str | None, code: int, message: str) -> None:
        error = JSONRPCError(jsonrpc="2.0", id=request_id, error=ErrorData(code=code, message=message))
        await self.write(error.model_dump_json(by_alias=True) + "\n")


def reject_constant(value: str):
    raise ValueError("Non-JSON numeric constant")


class GuardedInput:
    def __init__(self, stdin: anyio.AsyncFile[bytes], output: ProtocolOutput):
        self.stdin = stdin
        self.output = output

    def __aiter__(self):
        return self

    async def __anext__(self) -> bytes:
        while True:
            line = await self.stdin.readline()
            if not line:
                raise StopAsyncIteration
            try:
                payload = json.loads(line, parse_constant=reject_constant)
            except (ValueError, RecursionError):
                logger.info("Malformed JSON frame rejected")
                await self.output.error(None, PARSE_ERROR, "Parse error")
                continue
            request_id = None
            if isinstance(payload, dict):
                candidate = payload.get("id")
                if type(candidate) in (int, str):
                    request_id = candidate
                if "id" in payload and "method" in payload and type(candidate) not in (int, str):
                    # The SDK union can otherwise reinterpret an invalid-ID
                    # request as a notification by ignoring its extra id field.
                    await self.output.error(None, INVALID_REQUEST, "Invalid Request")
                    continue
            envelope = payload.copy() if isinstance(payload, dict) else payload
            if isinstance(envelope, dict):
                envelope.pop("params", None)
            try:
                jsonrpc_message_adapter.validate_python(envelope)
            except ValidationError:
                await self.output.error(request_id, INVALID_REQUEST, "Invalid Request")
                continue
            if isinstance(payload, dict) and "params" in payload and not isinstance(payload["params"], dict):
                if "id" in payload:  # Never answer notifications.
                    await self.output.error(request_id, INVALID_PARAMS, "Invalid params")
                continue
            try:
                jsonrpc_message_adapter.validate_python(payload)
            except ValidationError:
                await self.output.error(request_id, INVALID_REQUEST, "Invalid Request")
                continue
            return line
