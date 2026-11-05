"""SDK handlers with explicit protocol errors instead of tool error conversion."""

import hashlib
import json
import logging
from typing import Any, TextIO

from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp.shared.exceptions import MCPError
from mcp_types import (
    INTERNAL_ERROR, INVALID_PARAMS, CallToolRequestParams, CallToolResult,
    ListToolsResult, TextContent, Tool,
)
from pydantic import ConfigDict, ValidationError

from .models import CustomerLookup, RefundRequest
from .transport import GuardedInput, ProtocolOutput

logger = logging.getLogger(__name__)

_CUSTOMERS = {
    "CUST-00001": {"customer_id": "CUST-00001", "name": "Alex Example", "status": "active"},
    "CUST-00002": {"customer_id": "CUST-00002", "name": "Sam Example", "status": "active"},
}


class StrictCallParams(CallToolRequestParams):
    # Preserve official metadata/extensions while preventing name coercion.
    model_config = ConfigDict(strict=True, extra="allow")


def get_customer_record(customer_id: str) -> dict[str, Any]:
    request = CustomerLookup(customer_id=customer_id)
    record = _CUSTOMERS.get(request.customer_id)
    if record is None:
        return {"customer_id": request.customer_id, "found": False}
    return {"found": True, **record}


def trigger_refund(customer_id: str, amount: float, reason: str) -> dict[str, Any]:
    request = RefundRequest(customer_id=customer_id, amount=amount, reason=reason)
    if request.customer_id not in _CUSTOMERS:
        return {"customer_id": request.customer_id, "status": "customer_not_found", "mock": True}
    canonical = json.dumps(request.model_dump(), sort_keys=True, ensure_ascii=True, allow_nan=False)
    receipt = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return {**request.model_dump(), "refund_id": "MOCK-" + receipt, "status": "simulated", "mock": True}


_TOOLS = {
    "get_customer_record": (CustomerLookup, get_customer_record, "Look up a deterministic mock customer record."),
    "trigger_refund": (RefundRequest, trigger_refund, "Simulate a refund; no money is moved."),
}


async def list_tools(ctx, params) -> ListToolsResult:
    return ListToolsResult(tools=[
        Tool(name=name, description=description, input_schema=model.model_json_schema())
        for name, (model, _, description) in _TOOLS.items()
    ])


async def call_tool(ctx, params: StrictCallParams) -> CallToolResult:
    definition = _TOOLS.get(params.name)
    if definition is None:
        raise MCPError(INVALID_PARAMS, "Unknown tool")
    model, function, _ = definition
    try:
        arguments = model.model_validate(params.arguments if params.arguments is not None else {})
    except ValidationError:
        logger.info("Tool arguments rejected")
        raise MCPError(INVALID_PARAMS, "Invalid tool parameters") from None
    try:
        result = function(**arguments.model_dump())
        text = json.dumps(result, ensure_ascii=True, allow_nan=False, sort_keys=True)
        return CallToolResult(content=[TextContent(type="text", text=text)], structured_content=result)
    except Exception as exc:
        logger.error("Unexpected tool failure (%s)", type(exc).__name__)
        raise MCPError(INTERNAL_ERROR, "Internal server error") from None


def create_server() -> Server:
    server = Server("assessment-customers", version="1.0.0", on_list_tools=list_tools, on_call_tool=call_tool)
    server.add_request_handler("tools/call", StrictCallParams, call_tool)
    server.middleware.append(protocol_errors)
    return server


async def protocol_errors(ctx, call_next):
    """Cover SDK legacy catch-all code=0 for failures outside tool execution."""
    try:
        return await call_next(ctx)
    except MCPError:
        raise
    except ValidationError:
        raise MCPError(INVALID_PARAMS, "Invalid request parameters") from None
    except Exception as exc:
        logger.error("Unexpected request failure (%s)", type(exc).__name__)
        raise MCPError(INTERNAL_ERROR, "Internal server error") from None


async def serve(wire: TextIO) -> None:
    import anyio
    import sys

    output = ProtocolOutput(wire)
    # Decode each frame as JSON UTF-8, independent of Windows console codepage.
    stdin = anyio.wrap_file(sys.stdin.buffer)
    guarded = GuardedInput(stdin, output)
    server = create_server()
    logger.info("Customer MCP server starting (stdio)")
    async with stdio_server(stdin=guarded, stdout=output) as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())
