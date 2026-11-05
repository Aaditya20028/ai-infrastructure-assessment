"""Independent, deterministic local HTTP MCP-shaped fixture. No real keys."""

import json

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from .protocol import Envelope, ToolCall, load_json, rpc_error, usable_id

TOOLS = [
    {"name": "get_status", "description": "Return fixed mock status", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "admin_reset_key", "description": "Simulate a key reset without creating a key", "inputSchema": {"type": "object", "properties": {}}},
]


def create_mock_app() -> FastAPI:
    app = FastAPI(title="Local mock MCP downstream", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.calls = []  # In-memory spy for tests; never exposed via an endpoint.

    @app.post("/mcp")
    async def mcp(request: Request):
        try:
            payload = load_json(await request.body())
        except (ValueError, RecursionError):
            return rpc_error(None, -32700, "Parse error", 400)
        request_id = usable_id(payload)
        try:
            envelope = Envelope.model_validate(payload)
        except ValidationError:
            return rpc_error(request_id, -32600, "Invalid Request", 400)
        app.state.calls.append(payload)
        if envelope.method == "tools/list":
            return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": {"tools": TOOLS}})
        if envelope.method != "tools/call":
            return rpc_error(request_id, -32601, "Method not found", 200)
        try:
            params = ToolCall.model_validate(envelope.params)
        except ValidationError:
            return rpc_error(request_id, -32602, "Invalid params", 200)
        if params.name == "get_status":
            result = {"status": "ready", "mock": True}
        elif params.name == "admin_reset_key":
            result = {"status": "simulated", "key_reset": True, "mock": True}
        else:
            return rpc_error(request_id, -32602, "Unknown tool", 200)
        return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": {
            "content": [{"type": "text", "text": json.dumps(result, sort_keys=True)}], "isError": False,
        }})

    return app
