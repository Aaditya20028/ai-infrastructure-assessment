import asyncio
import json

import httpx
import pytest

from .conftest import bearer, open_gateway, rpc


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 401, 403, 404, 429, 500, 503])
async def test_downstream_http_errors_and_redirects(tokens, status):
    def handler(request):
        return httpx.Response(status, text="SENSITIVE_DOWNSTREAM_BODY", headers={"Location": "http://untrusted.invalid/", "Content-Type": "text/plain"})

    async with open_gateway(tokens, handler=handler) as gateway:
        response = await gateway.client.post("/mcp", json=rpc(request_id="failure"), headers=bearer(tokens["viewer"]))
        assert response.status_code == 502
        assert response.json() == {"jsonrpc": "2.0", "id": "failure", "error": {"code": -32002, "message": "Downstream failure"}}
        assert "SENSITIVE_DOWNSTREAM_BODY" not in response.text
        assert len(gateway.spy.requests) == 1  # No redirect and no retry.


@pytest.mark.asyncio
@pytest.mark.parametrize("content", [
    b"not json", b"[]", b'{"jsonrpc":"1.0","id":1,"result":{}}',
    b'{"jsonrpc":"2.0","id":"1","result":{}}',
    b'{"jsonrpc":"2.0","id":true,"result":{}}',
    b'{"jsonrpc":"2.0","id":1,"result":{},"error":{"code":-1,"message":"bad"}}',
    b'{"jsonrpc":"2.0","id":1}', b'{"jsonrpc":"2.0","id":1,"result":[]}',
    b'{"jsonrpc":"2.0","id":1,"error":{"code":"-1","message":"bad"}}',
    b'{"jsonrpc":"2.0","id":1,"result":{"value":Infinity}}',
])
async def test_malformed_downstream_responses(tokens, content):
    def handler(request):
        return httpx.Response(200, content=content, headers={"Content-Type": "application/json"})

    async with open_gateway(tokens, handler=handler) as gateway:
        response = await gateway.client.post("/mcp", json=rpc(), headers=bearer(tokens["viewer"]))
        assert response.status_code == 502 and response.json()["error"]["code"] == -32002
        assert response.json()["id"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("exception,status,code", [
    (httpx.ReadTimeout("sensitive"), 504, -32003),
    (httpx.ConnectTimeout("sensitive"), 504, -32003),
    (httpx.ConnectError("sensitive"), 502, -32002),
    (httpx.RemoteProtocolError("sensitive"), 502, -32002),
    (RuntimeError("sensitive"), 500, -32603),
])
async def test_transport_failures_are_sanitized(tokens, caplog, exception, status, code):
    def handler(request):
        raise exception

    async with open_gateway(tokens, handler=handler) as gateway:
        response = await gateway.client.post("/mcp", json=rpc(), headers=bearer(tokens["viewer"]))
        assert response.status_code == status and response.json()["error"]["code"] == code
        assert "sensitive" not in response.text and "sensitive" not in caplog.text
        assert all(token not in caplog.text for token in tokens.values())
        assert len(gateway.spy.requests) == 1


@pytest.mark.asyncio
async def test_total_timeout_cancels_hung_downstream(tokens):
    cancelled = asyncio.Event()

    async def handler(request):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    async with open_gateway(tokens, handler=handler, timeout_seconds=0.02) as gateway:
        response = await gateway.client.post("/mcp", json=rpc(request_id=0), headers=bearer(tokens["viewer"]))
        assert response.status_code == 504
        assert response.json()["id"] == 0 and response.json()["error"]["code"] == -32003
        assert cancelled.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize("wrong_type,too_large", [(True, False), (False, True)])
async def test_upstream_content_type_and_size_limits(tokens, wrong_type, too_large):
    def handler(request):
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {"padding": "x" * 100}},
                              headers={"Content-Type": "text/html" if wrong_type else "application/json"})

    async with open_gateway(tokens, handler=handler, max_response_bytes=32 if too_large else 1024) as gateway:
        response = await gateway.client.post("/mcp", json=rpc(), headers=bearer(tokens["viewer"]))
        assert response.status_code == 502


@pytest.mark.asyncio
async def test_response_bytes_preserved_and_backend_cookies_not_reused(tokens):
    raw = b'{ "jsonrpc": "2.0", "id": 1, "result": {"tools": [], "_meta":{"opaque":true}} }'

    def handler(request):
        assert "authorization" not in request.headers and "cookie" not in request.headers
        return httpx.Response(200, content=raw, headers={"Content-Type": "application/json", "Set-Cookie": "backend_session=sensitive"})

    async with open_gateway(tokens, handler=handler) as gateway:
        for role in ["admin", "viewer"]:
            response = await gateway.client.post("/mcp", json=rpc(method="tools/list"), headers=bearer(tokens[role]))
            assert response.content == raw
            assert "set-cookie" not in response.headers
        assert len(gateway.spy.requests) == 2


@pytest.mark.asyncio
async def test_denial_and_auth_failure_do_not_log_credentials_or_arguments(gateway, tokens, caplog):
    payload = rpc(name="admin_reset_key")
    payload["params"]["arguments"] = {"private": "SENSITIVE_ARGUMENT"}
    await gateway.client.post("/mcp", json=payload, headers=bearer(tokens["viewer"]))
    await gateway.client.post("/mcp", json=payload, headers=bearer("SENSITIVE_UNKNOWN_TOKEN"))
    assert "SENSITIVE_ARGUMENT" not in caplog.text and "SENSITIVE_UNKNOWN_TOKEN" not in caplog.text
    assert all(token not in caplog.text for token in tokens.values())
    assert gateway.spy.requests == []
