"""Small JSON-RPC request/response boundary for this HTTP proxy subset."""

import json
import math
from typing import Any, Literal

from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, ValidationError


class Envelope(BaseModel):
    model_config = ConfigDict(strict=True, extra="allow")
    jsonrpc: Literal["2.0"]
    method: StrictStr = Field(min_length=1)
    id: StrictInt | StrictStr | None = None
    params: Any = None


class ToolCall(BaseModel):
    model_config = ConfigDict(strict=True, extra="allow")
    name: str = Field(min_length=1)
    arguments: dict[str, Any] | None = None


class ErrorObject(BaseModel):
    model_config = ConfigDict(strict=True, extra="allow")
    code: StrictInt
    message: str


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON member")
        result[key] = value
    return result


def finite_float(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Non-finite JSON number")
    return result


def reject_constant(value):
    raise ValueError("Non-JSON numeric constant")


def load_json(body: bytes):
    return json.loads(body, object_pairs_hook=unique_object, parse_float=finite_float, parse_constant=reject_constant)


def usable_id(payload):
    candidate = payload.get("id") if isinstance(payload, dict) else None
    return candidate if type(candidate) in (int, str) else None


def rpc_error(request_id, code: int, message: str, status: int, *, notification=False) -> Response:
    if notification:
        return Response(status_code=204)
    headers = {"WWW-Authenticate": "Bearer"} if status == 401 else None
    return JSONResponse({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}, status_code=status, headers=headers)


def validate_response(body: bytes, request_id):
    payload = load_json(body)
    if not isinstance(payload, dict) or payload.get("jsonrpc") != "2.0":
        raise ValueError("Invalid downstream envelope")
    if type(payload.get("id")) is not type(request_id) or payload.get("id") != request_id:
        raise ValueError("Mismatched downstream ID")
    if ("result" in payload) == ("error" in payload):
        raise ValueError("Invalid downstream response")
    if "error" in payload:
        ErrorObject.model_validate(payload["error"])
    elif not isinstance(payload["result"], dict):
        raise ValueError("MCP result must be an object")
