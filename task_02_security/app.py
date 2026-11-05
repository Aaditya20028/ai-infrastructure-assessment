"""Authenticated HTTP/JSON-RPC request-response gateway."""

from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, Request
from fastapi.responses import Response
import httpx
from pydantic import ValidationError

from .auth import AuthenticationError, authenticate
from .config import Settings
from .policy import may_call_tool
from .protocol import Envelope, ToolCall, load_json, rpc_error, usable_id
from .proxy import DownstreamFailure, DownstreamTimeout, Forwarder

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    settings = settings if settings is not None else Settings.from_env()

    @asynccontextmanager
    async def lifespan(app):
        async with httpx.AsyncClient(
            transport=transport, timeout=settings.timeout_seconds, follow_redirects=False, trust_env=False,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        ) as client:
            app.state.forwarder = Forwarder(client, settings)
            yield

    app = FastAPI(title="MCP Security Gateway", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.post("/mcp")
    async def gateway(request: Request):
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > settings.max_request_bytes:
                return rpc_error(None, -32600, "Request too large", 413)
        try:
            payload = load_json(bytes(body))
        except (ValueError, RecursionError):
            return rpc_error(None, -32700, "Parse error", 400)
        request_id = usable_id(payload)
        try:
            envelope = Envelope.model_validate(payload)
            if "id" in envelope.model_fields_set and envelope.id is None:
                raise ValueError("Null request ID")
        except (ValidationError, ValueError):
            return rpc_error(request_id, -32600, "Invalid Request", 400)
        notification = "id" not in envelope.model_fields_set
        try:
            role = authenticate(request.headers.getlist("authorization"), settings)
        except AuthenticationError:
            # Authentication is an HTTP failure even for notifications.
            if notification:
                return Response(status_code=401, headers={"WWW-Authenticate": "Bearer"})
            return rpc_error(request_id, -32000, "Unauthorized", 401)
        if envelope.method not in {"tools/list", "tools/call"}:
            return rpc_error(request_id, -32601, "Method not found", 400, notification=notification)
        if ("params" in envelope.model_fields_set and not isinstance(envelope.params, dict)):
            return rpc_error(request_id, -32602, "Invalid params", 400, notification=notification)
        if envelope.method == "tools/call":
            try:
                params = ToolCall.model_validate(envelope.params)
            except ValidationError:
                return rpc_error(request_id, -32602, "Invalid params", 400, notification=notification)
            if not may_call_tool(role, params.name):
                return rpc_error(request_id, -32001, "Unauthorized Tool Call", 403, notification=notification)
        if notification:
            # Tool operations are requests in MCP; never execute notifications.
            return Response(status_code=204)
        try:
            result = await app.state.forwarder.forward(bytes(body), request_id)
            return Response(content=result, media_type="application/json")
        except DownstreamTimeout:
            logger.warning("Downstream timeout")
            return rpc_error(request_id, -32003, "Downstream timeout", 504)
        except DownstreamFailure:
            logger.warning("Downstream failure")
            return rpc_error(request_id, -32002, "Downstream failure", 502)
        except Exception as exc:
            logger.error("Gateway failure (%s)", type(exc).__name__)
            return rpc_error(request_id, -32603, "Internal server error", 500)

    return app
