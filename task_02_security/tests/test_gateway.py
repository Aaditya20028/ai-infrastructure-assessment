import json

import pytest

from .conftest import bearer, open_gateway, rpc


@pytest.mark.asyncio
@pytest.mark.parametrize("role,name", [("admin", "admin_reset_key"), ("admin", "get_status"), ("viewer", "get_status")])
async def test_allowed_calls_reach_mock(gateway, tokens, role, name):
    response = await gateway.client.post("/mcp", json=rpc(name=name), headers=bearer(tokens[role]))
    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == 1 and payload["jsonrpc"] == "2.0"
    result = json.loads(payload["result"]["content"][0]["text"])
    assert result["mock"] is True
    assert result["status"] == ("simulated" if name.startswith("admin_") else "ready")
    assert len(gateway.spy.requests) == len(gateway.downstream.state.calls) == 1


@pytest.mark.asyncio
async def test_denied_call_never_reaches_downstream_even_with_role_claim(gateway, tokens):
    payload = rpc(name="admin_reset_key", request_id="denied-id")
    payload["params"]["role"] = "admin"
    response = await gateway.client.post("/mcp", json=payload, headers={**bearer(tokens["viewer"]), "X-Role": "admin"})
    assert response.status_code == 403
    assert response.json() == {"jsonrpc": "2.0", "id": "denied-id", "error": {"code": -32001, "message": "Unauthorized Tool Call"}}
    assert gateway.spy.requests == [] and gateway.downstream.state.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["admin", "viewer"])
async def test_tools_list_forwarding_is_transparent(gateway, tokens, role):
    raw = b'{ "jsonrpc": "2.0", "id": "catalog", "method": "tools/list", "params": {"cursor":"opaque","_meta":{"test":true}} }'
    response = await gateway.client.post("/mcp", content=raw, headers=bearer(tokens[role]))
    assert response.status_code == 200
    assert {tool["name"] for tool in response.json()["result"]["tools"]} == {"get_status", "admin_reset_key"}
    assert gateway.spy.requests[0].content == raw
    assert gateway.downstream.state.calls[0] == json.loads(raw)


@pytest.mark.asyncio
@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer"}, {"Authorization": "Basic fake"}, {"Authorization": "Bearer admin"}, {"Authorization": "Bearer unverified.viewer.claim"}])
async def test_missing_or_invalid_authentication(gateway, headers):
    response = await gateway.client.post("/mcp", json=rpc(request_id=0), headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {"jsonrpc": "2.0", "id": 0, "error": {"code": -32000, "message": "Unauthorized"}}
    assert gateway.spy.requests == []


@pytest.mark.asyncio
async def test_duplicate_auth_headers_rejected(gateway, tokens):
    response = await gateway.client.post("/mcp", json=rpc(), headers=[("Authorization", "Bearer " + tokens["viewer"]), ("Authorization", "Bearer " + tokens["admin"])])
    assert response.status_code == 401 and gateway.spy.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("request_id", [0, -1, 123, "123", "", "unicode-é"])
async def test_request_id_type_preserved(gateway, tokens, request_id):
    response = await gateway.client.post("/mcp", json=rpc(request_id=request_id), headers=bearer(tokens["viewer"]))
    assert response.status_code == 200
    assert response.json()["id"] == request_id and type(response.json()["id"]) is type(request_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("raw,code,expected_id", [
    (b'{broken', -32700, None), (b'null', -32600, None), (b'[]', -32600, None),
    (b'{"jsonrpc":"1.0","id":"bad","method":"tools/list"}', -32600, "bad"),
    (b'{"jsonrpc":"2.0","id":true,"method":"tools/list"}', -32600, None),
    (b'{"jsonrpc":"2.0","id":null,"method":"tools/list"}', -32600, None),
    (b'{"jsonrpc":"2.0","id":1.5,"method":"tools/list"}', -32600, None),
    (b'{"jsonrpc":"2.0","id":"missing-method"}', -32600, "missing-method"),
    (b'{"jsonrpc":"2.0","id":1,"method":"tools/call","params":[]}', -32602, 1),
    (b'{"jsonrpc":"2.0","id":1,"method":"tools/call","params":null}', -32602, 1),
    (b'{"jsonrpc":"2.0","id":1,"method":"tools/call"}', -32602, 1),
    (b'{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":4}}', -32602, 1),
    (b'{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":""}}', -32602, 1),
    (b'{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"get_status","arguments":[]}}', -32602, 1),
    (b'{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"admin_reset_key","name":"get_status"}}', -32700, None),
    (b'{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"get_status","arguments":{"value":NaN}}}', -32700, None),
])
async def test_malformed_requests_never_forward(gateway, tokens, raw, code, expected_id):
    response = await gateway.client.post("/mcp", content=raw, headers=bearer(tokens["admin"]))
    assert response.status_code == 400
    assert response.json()["error"]["code"] == code
    assert response.json()["id"] == expected_id
    assert gateway.spy.requests == []


@pytest.mark.asyncio
async def test_unknown_method_is_not_an_authorization_bypass(gateway, tokens):
    response = await gateway.client.post("/mcp", json=rpc(method="custom/execute"), headers=bearer(tokens["viewer"]))
    assert response.status_code == 400 and response.json()["error"]["code"] == -32601
    assert gateway.spy.requests == []


@pytest.mark.asyncio
async def test_unknown_permitted_tool_preserves_downstream_rpc_error(gateway, tokens):
    response = await gateway.client.post("/mcp", json=rpc(name="unknown"), headers=bearer(tokens["viewer"]))
    assert response.status_code == 200
    assert response.json()["error"] == {"code": -32602, "message": "Unknown tool"}
    assert len(gateway.spy.requests) == 1


@pytest.mark.asyncio
async def test_notifications_never_execute_or_emit_rpc_responses(gateway, tokens):
    for name in ["get_status", "admin_reset_key"]:
        payload = rpc(name=name)
        del payload["id"]
        response = await gateway.client.post("/mcp", json=payload, headers=bearer(tokens["viewer"]))
        assert response.status_code == 204 and response.content == b""
    response = await gateway.client.post("/mcp", json=payload)
    assert response.status_code == 401 and response.content == b""
    assert gateway.spy.requests == []


@pytest.mark.asyncio
async def test_request_body_size_is_bounded(tokens):
    async with open_gateway(tokens, max_request_bytes=32) as gateway:
        response = await gateway.client.post("/mcp", content=b"x" * 33, headers=bearer(tokens["viewer"]))
        assert response.status_code == 413 and response.json()["error"]["code"] == -32600
        assert gateway.spy.requests == []


@pytest.mark.asyncio
async def test_user_credentials_and_headers_are_never_forwarded(gateway, tokens):
    response = await gateway.client.post("/mcp", json=rpc(), headers={
        **bearer(tokens["viewer"]), "Cookie": "session=sensitive", "X-Api-Key": "sensitive", "X-Role": "admin",
    })
    assert response.status_code == 200
    headers = gateway.spy.requests[0].headers
    assert all(name not in headers for name in ["authorization", "cookie", "x-api-key", "x-role"])
