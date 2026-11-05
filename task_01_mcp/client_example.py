"""Run with python -m task_01_mcp.client_example from the repository root."""

import asyncio
import json
from pathlib import Path
import sys

from mcp import Client
from mcp.client.stdio import StdioServerParameters
from mcp.shared.exceptions import MCPError


async def main() -> None:
    parameters = StdioServerParameters(
        command=sys.executable, args=["-m", "task_01_mcp"], cwd=Path(__file__).resolve().parents[1],
    )
    async with Client(parameters, read_timeout_seconds=15) as client:
        print("Tools:", [tool.name for tool in (await client.list_tools()).tools])
        lookup = await client.call_tool("get_customer_record", {"customer_id": "CUST-00001"})
        print("Lookup:", json.dumps(lookup.structured_content, sort_keys=True))
        refund = await client.call_tool("trigger_refund", {
            "customer_id": "CUST-00001", "amount": 12.5, "reason": "Product damaged",
        })
        print("Refund:", json.dumps(refund.structured_content, sort_keys=True))
        try:
            await client.call_tool("trigger_refund", {
                "customer_id": "CUST-00001", "amount": 0, "reason": "Product damaged",
            })
        except MCPError as exc:
            print("Invalid refund:", exc.code, exc.message)
        else:
            raise AssertionError("Expected an invalid-params protocol error")


if __name__ == "__main__":
    asyncio.run(main())
