from pathlib import Path
import sys

from mcp import Client
from mcp.client.stdio import StdioServerParameters
from mcp.shared.exceptions import MCPError
import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_official_sdk_stdio_client(mode):
    parameters = StdioServerParameters(command=sys.executable, args=["-m", "task_01_mcp"], cwd=Path(__file__).resolve().parents[2])
    async with Client(parameters, mode=mode, read_timeout_seconds=15) as client:
        tools = await client.list_tools()
        assert {tool.name for tool in tools.tools} == {"get_customer_record", "trigger_refund"}
        result = await client.call_tool("get_customer_record", {"customer_id": "CUST-00001"})
        assert not result.is_error
        assert result.structured_content["found"] is True
        with pytest.raises(MCPError) as error:
            await client.call_tool("trigger_refund", {"customer_id": "CUST-00001", "amount": 0, "reason": "Product damaged"})
        assert error.value.code == -32602
