"""Clients of task public interfaces only; no replacement backend behavior."""

import asyncio
from contextlib import ExitStack
import json
from pathlib import Path
import secrets
import sys
import tempfile

import httpx

from .processes import DemoFailure, ROOT, Service, available_ports, child_environment

MODULES = {1: "task_01_mcp", 2: "task_02_security", 3: "task_03_streaming", 4: "task_04_limiter"}


def require(condition):
    if not condition:
        raise DemoFailure("Backend did not satisfy the selected demonstration")


async def task_one():
    from mcp import Client
    from mcp.client.stdio import StdioServerParameters

    parameters = StdioServerParameters(command=sys.executable, args=["-m", MODULES[1]], cwd=ROOT, env=child_environment())
    async with Client(parameters, read_timeout_seconds=15) as client:
        tools = await client.list_tools()
        names = [tool.name for tool in tools.tools]
        require(set(names) == {"get_customer_record", "trigger_refund"})
        record = await client.call_tool("get_customer_record", {"customer_id": "CUST-00001"})
        refund = await client.call_tool("trigger_refund", {"customer_id": "CUST-00001", "amount": 12.5, "reason": "Product damaged"})
        require(not record.is_error and not refund.is_error)
        return {"task": 1, "transport": "stdio", "tools": names,
                "customer": record.structured_content, "refund": refund.structured_content}


def rpc(client, url, token, method, request_id, name=None):
    payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": {}}
    if name is not None:
        payload["params"] = {"name": name, "arguments": {}}
    response = client.post(url, json=payload, headers={"Authorization": "Bearer " + token})
    body = response.json()
    require(body.get("jsonrpc") == "2.0" and body.get("id") == request_id)
    return response.status_code, body


def task_two():
    mock_port, gateway_port = available_ports(2)
    admin, viewer = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    env = child_environment()
    env.update(TASK2_TOKEN_ROLES=json.dumps({admin: "admin", viewer: "viewer"}),
               TASK2_UPSTREAM_URL=f"http://127.0.0.1:{mock_port}/mcp")
    with ExitStack() as stack:
        stack.enter_context(Service(MODULES[2], ["--mock", "--port", str(mock_port)], env))
        stack.enter_context(Service(MODULES[2], ["--port", str(gateway_port)], env))
        with httpx.Client(timeout=10, trust_env=False) as client:
            url = f"http://127.0.0.1:{gateway_port}/mcp"
            list_status, listed = rpc(client, url, viewer, "tools/list", "catalog")
            denied_status, denied = rpc(client, url, viewer, "tools/call", "denied", "admin_reset_key")
            allowed_status, allowed = rpc(client, url, admin, "tools/call", "admin", "admin_reset_key")
            viewer_status, permitted = rpc(client, url, viewer, "tools/call", "viewer", "get_status")
        require(list_status == allowed_status == viewer_status == 200 and denied_status == 403)
        require(denied.get("error", {}).get("code") == -32001)
        require("result" in listed and "result" in allowed and "result" in permitted)
        require(not allowed["result"].get("isError", False) and not permitted["result"].get("isError", False))
        require({tool["name"] for tool in listed["result"]["tools"]} == {"get_status", "admin_reset_key"})
        return {"task": 2, "tools_list": listed, "viewer_admin_denial": denied,
                "admin_call": allowed, "viewer_call": permitted}


def consume_sse(response):
    """Read SSE as a client; this does not parse/redact provider text."""
    data, event_type, parts = [], "message", []
    done = False
    size = 0
    for line in response.iter_lines():
        if not line:
            if data:
                require(event_type == "message")
                payload = "\n".join(data)
                if payload == "[DONE]":
                    done = True
                    break
                body = json.loads(payload)
                text = body["choices"][0]["delta"]["content"]
                require(isinstance(text, str))
                size += len(text)
                require(size <= 65536)
                parts.append(text)
            data, event_type = [], "message"
        elif line.startswith("data:"):
            data.append(line[5:].removeprefix(" "))
        elif line.startswith("event:"):
            event_type = line[6:].removeprefix(" ")
    require(done)
    return "".join(parts)


def task_three():
    mock_port, gateway_port = available_ports(2)
    env = child_environment()
    env["TASK3_PROVIDER_URL"] = f"http://127.0.0.1:{mock_port}/v1/generate"
    with ExitStack() as stack:
        stack.enter_context(Service(MODULES[3], ["--mock", "--port", str(mock_port), "--delay", "0.05"], env))
        stack.enter_context(Service(MODULES[3], ["--port", str(gateway_port)], env))
        with httpx.Client(timeout=10, trust_env=False) as client:
            with client.stream("POST", f"http://127.0.0.1:{gateway_port}/v1/generate", json={"prompt": "demo"}) as response:
                response.raise_for_status()
                text = consume_sse(response)
        # Check the real result before printing it; never manufacture a marker.
        require(text.count("[REDACTED]") == 3)
        require(not any(fragment in text for fragment in ("alice@", "123-45", "4111")))
        return {"task": 3, "text": text, "completion_seen": True}


def task_four():
    primary_port, secondary_port, gateway_port = available_ports(3)
    key = secrets.token_urlsafe(32)
    env = child_environment()
    with tempfile.TemporaryDirectory(prefix="optional-task4-") as folder, ExitStack() as stack:
        env.update(TASK4_API_KEYS=json.dumps({key: "optional-demo-tenant"}),
                   TASK4_DATABASE=str(Path(folder) / "quota.sqlite3"),
                   TASK4_PRIMARY_URL=f"http://127.0.0.1:{primary_port}/v1/complete",
                   TASK4_SECONDARY_URL=f"http://127.0.0.1:{secondary_port}/v1/complete")
        stack.enter_context(Service(MODULES[4], ["--service", "primary", "--port", str(primary_port), "--behavior", "rate_limit"], env))
        stack.enter_context(Service(MODULES[4], ["--service", "secondary", "--port", str(secondary_port)], env))
        stack.enter_context(Service(MODULES[4], ["--port", str(gateway_port)], env))
        with httpx.Client(timeout=10, trust_env=False) as client:
            url = f"http://127.0.0.1:{gateway_port}/v1/complete"
            headers = {"Authorization": "Bearer " + key}
            response = client.post(url, json={"prompt": "hello", "max_output_tokens": 64}, headers=headers)
            response.raise_for_status()
            body = response.json()
            require(body.get("provider") == "secondary" and body.get("fallback_reason") == "primary_rate_limit")
            denied = client.post(url, json={"prompt": "hello", "max_output_tokens": 50000}, headers=headers)
            require(denied.status_code == 429 and denied.json().get("error", {}).get("code") == "quota_exceeded")
        return {"task": 4, "completion": body, "quota_denial": denied.json()}


def run(task):
    if task == 1:
        return asyncio.run(task_one())
    return {2: task_two, 3: task_three, 4: task_four}[task]()
