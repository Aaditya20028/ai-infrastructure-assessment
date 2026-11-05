import asyncio
from contextlib import closing
import json
import re
import sqlite3
import threading

import httpx
import pytest

from task_04_limiter.providers import Deadlines, PRIMARY_TIMEOUT_SECONDS
from task_04_limiter.storage import StoreUnavailable
from .conftest import bearer, open_gateway, provider_reply, prompt_with_tokens


def assert_public_error(response, code, status):
    assert response.status_code == status
    payload = response.json()
    assert set(payload) == {"error"}
    assert set(payload["error"]) == {"code", "message", "request_id"}
    assert payload["error"]["code"] == code
    assert re.fullmatch(r"[a-f0-9]{32}", payload["error"]["request_id"])
    assert "SENSITIVE" not in response.text and "Traceback" not in response.text


@pytest.mark.asyncio
async def test_under_limit_primary_success_reconciles_and_never_calls_backup(gateway, keys):
    response = await gateway.client.post("/v1/complete", json={"prompt": "hello", "max_output_tokens": 100}, headers=bearer(keys["a"]))
    assert response.status_code == 200
    assert response.json()["provider"] == "primary" and response.json()["fallback_reason"] is None
    assert response.json()["usage"]["total_tokens"] == 2
    assert response.json()["usage"]["counting_method"] == "tiktoken_cl100k_base_v1"
    assert response.json()["usage"]["encoding"] == "cl100k_base"
    assert gateway.store.usage(gateway.tenant(keys["a"])) == 2
    assert [request.url.host for request in gateway.requests] == ["primary"]
    assert all(name not in gateway.requests[0].headers for name in ("authorization", "cookie", "x-tenant"))


@pytest.mark.asyncio
async def test_exact_limit_and_above_limit_are_enforced_before_forwarding(tmp_path, keys, clock):
    async with open_gateway(tmp_path / "quota.db", keys, clock, handler=lambda req: provider_reply(req, text="x")) as gateway:
        result = await gateway.client.post("/v1/complete", json={"prompt": prompt_with_tokens(49999), "max_output_tokens": 1}, headers=bearer(keys["a"]))
        assert result.status_code == 200 and result.json()["usage"]["total_tokens"] == 50000
        denied = await gateway.client.post("/v1/complete", json={"prompt": "x", "max_output_tokens": 1}, headers=bearer(keys["a"]))
        assert_public_error(denied, "quota_exceeded", 429)
        independent = await gateway.client.post("/v1/complete", json={"prompt": "x", "max_output_tokens": 1}, headers=bearer(keys["b"]))
        assert independent.status_code == 200
        assert len(gateway.requests) == 2


@pytest.mark.asyncio
async def test_oversize_reservation_without_prior_usage(gateway, keys):
    response = await gateway.client.post("/v1/complete", json={"prompt": prompt_with_tokens(50000), "max_output_tokens": 1}, headers=bearer(keys["a"]))
    assert_public_error(response, "quota_exceeded", 429)
    assert gateway.requests == []


@pytest.mark.asyncio
async def test_admission_uses_tokens_even_when_utf8_bytes_exceed_quota(tmp_path, keys, clock):
    prompt = "😀\n" * 10000
    assert len(prompt.encode("utf-8")) == 50000
    async with open_gateway(tmp_path / "quota.db", keys, clock, handler=lambda req: provider_reply(req, text="x")) as gateway:
        response = await gateway.client.post("/v1/complete", json={"prompt": prompt, "max_output_tokens": 1}, headers=bearer(keys["a"]))
        assert response.status_code == 200
        assert response.json()["usage"]["input_tokens"] == 30000
        assert response.json()["usage"]["total_tokens"] == 30001
        assert gateway.store.usage(gateway.tenant(keys["a"])) == 30001


@pytest.mark.asyncio
async def test_primary_429_immediate_fallback_charges_one_logical_request(tmp_path, keys, clock):
    def handler(request):
        return httpx.Response(429, text="SENSITIVE_RATE_LIMIT") if request.url.host == "primary" else provider_reply(request)

    async with open_gateway(tmp_path / "quota.db", keys, clock, handler=handler) as gateway:
        response = await gateway.client.post("/v1/complete", json={"prompt": "hello", "max_output_tokens": 10}, headers=bearer(keys["a"]))
        assert response.status_code == 200
        assert response.json()["provider"] == "secondary" and response.json()["fallback_reason"] == "primary_rate_limit"
        assert [request.url.host for request in gateway.requests] == ["primary", "secondary"]
        assert gateway.store.usage(gateway.tenant(keys["a"])) == 2
        with closing(sqlite3.connect(gateway.store.path)) as connection:
            assert connection.execute("SELECT COUNT(*) FROM reservations").fetchone()[0] == 1


@pytest.mark.asyncio
async def test_exact_3000ms_deadline_and_late_primary_cannot_overwrite(tmp_path, keys, clock):
    started = asyncio.Event()
    release_late = asyncio.Event()
    cancelled = asyncio.Event()
    waits = []

    async def handler(request):
        if request.url.host == "primary":
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                await release_late.wait()  # Simulate a finite noncooperative SDK.
            return provider_reply(request, text="late")
        return provider_reply(request, text="ok")

    async def controlled_wait(tasks, *, timeout, return_when):
        waits.append(timeout)
        if len(waits) == 1:
            await started.wait()
            clock.advance(timeout)
            return set(), tasks
        return await asyncio.wait(tasks, timeout=timeout, return_when=return_when)

    deadlines = Deadlines(clock=clock, waiter=controlled_wait)
    async with open_gateway(tmp_path / "quota.db", keys, clock, handler=handler, deadlines=deadlines) as gateway:
        response = await gateway.client.post("/v1/complete", json={"prompt": "hello", "max_output_tokens": 10}, headers=bearer(keys["a"]))
        assert waits[0] == PRIMARY_TIMEOUT_SECONDS == 3.0
        assert response.status_code == 200 and response.json()["text"] == "ok"
        assert response.json()["provider"] == "secondary" and response.json()["fallback_reason"] == "primary_timeout"
        assert cancelled.is_set()
        usage = gateway.store.usage(gateway.tenant(keys["a"]))
        release_late.set()
        await asyncio.gather(*list(deadlines.inflight))
        assert response.json()["text"] == "ok" and gateway.store.usage(gateway.tenant(keys["a"])) == usage == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("status,expected", [(400, 502), (401, 502), (403, 502), (408, 502), (500, 502), (502, 502), (503, 503)])
async def test_other_primary_statuses_do_not_broaden_fallback(tmp_path, keys, clock, status, expected):
    async with open_gateway(tmp_path / "quota.db", keys, clock, handler=lambda req: httpx.Response(status, text="SENSITIVE_UPSTREAM")) as gateway:
        response = await gateway.client.post("/v1/complete", json={"prompt": "x", "max_output_tokens": 10}, headers=bearer(keys["a"]))
        assert response.status_code == expected and "SENSITIVE" not in response.text
        assert [request.url.host for request in gateway.requests] == ["primary"]
        assert gateway.store.usage(gateway.tenant(keys["a"])) == 11


@pytest.mark.asyncio
@pytest.mark.parametrize("status,code,http_status", [(429, "providers_unavailable", 503), (503, "providers_unavailable", 503), (500, "provider_error", 502)])
async def test_secondary_and_both_provider_failures_are_sanitized(tmp_path, keys, clock, status, code, http_status, caplog):
    def handler(request):
        return httpx.Response(429 if request.url.host == "primary" else status, text="SENSITIVE_STACK_TRACE")

    async with open_gateway(tmp_path / "quota.db", keys, clock, handler=handler) as gateway:
        response = await gateway.client.post("/v1/complete", json={"prompt": "hello", "max_output_tokens": 10}, headers=bearer(keys["a"]))
        assert_public_error(response, code, http_status)
        assert len(gateway.requests) == 2
        assert gateway.store.usage(gateway.tenant(keys["a"])) == 11  # Full one reserve, never two.
    assert "SENSITIVE" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [httpx.ConnectError("SENSITIVE_URL"), RuntimeError("SENSITIVE_STACK")])
async def test_unexpected_and_network_failures_are_sanitized(tmp_path, keys, clock, failure, caplog):
    def handler(request):
        raise failure

    async with open_gateway(tmp_path / "quota.db", keys, clock, handler=handler) as gateway:
        response = await gateway.client.post("/v1/complete", json={"prompt": "x"}, headers=bearer(keys["a"]))
        assert_public_error(response, "provider_error", 502)
        assert len(gateway.requests) == 1
    assert "SENSITIVE" not in caplog.text


@pytest.mark.asyncio
async def test_secondary_timeout_is_explicit_and_sanitized(tmp_path, keys, clock):
    def handler(request):
        if request.url.host == "primary":
            return httpx.Response(429)
        raise httpx.ReadTimeout("SENSITIVE_TIMEOUT")

    async with open_gateway(tmp_path / "quota.db", keys, clock, handler=handler) as gateway:
        result = await gateway.client.post("/v1/complete", json={"prompt": "x"}, headers=bearer(keys["a"]))
        assert_public_error(result, "provider_timeout", 504)
        assert len(gateway.requests) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    {"text": "word " * 6}, {"text": "ok", "usage": {"input_tokens": 0, "output_tokens": 0}},
    {"text": "ok", "usage": {"input_tokens": 1, "output_tokens": -1}},
    {"text": "ok", "usage": {"input_tokens": 1, "output_tokens": 99}},
])
async def test_invalid_usage_keeps_full_reservation_and_does_not_fallback(tmp_path, keys, clock, payload):
    async with open_gateway(tmp_path / "quota.db", keys, clock, handler=lambda req: httpx.Response(200, json=payload)) as gateway:
        result = await gateway.client.post("/v1/complete", json={"prompt": "x", "max_output_tokens": 5}, headers=bearer(keys["a"]))
        assert_public_error(result, "invalid_provider_response", 502)
        assert gateway.store.usage(gateway.tenant(keys["a"])) == 6 and len(gateway.requests) == 1


@pytest.mark.asyncio
async def test_missing_provider_usage_uses_measured_contract(tmp_path, keys, clock):
    async with open_gateway(tmp_path / "quota.db", keys, clock, handler=lambda req: provider_reply(req, usage=False)) as gateway:
        result = await gateway.client.post("/v1/complete", json={"prompt": "café", "max_output_tokens": 5}, headers=bearer(keys["a"]))
        assert result.status_code == 200 and result.json()["usage"]["total_tokens"] == 3


@pytest.mark.asyncio
async def test_ledger_persists_across_application_restart(tmp_path, keys, clock):
    path = tmp_path / "persistent.db"
    async with open_gateway(path, keys, clock, handler=lambda req: provider_reply(req, text="x")) as first:
        response = await first.client.post("/v1/complete", json={"prompt": prompt_with_tokens(49999), "max_output_tokens": 1}, headers=bearer(keys["a"]))
        assert response.status_code == 200
    async with open_gateway(path, keys, clock) as second:
        response = await second.client.post("/v1/complete", json={"prompt": "x"}, headers=bearer(keys["a"]))
        assert_public_error(response, "quota_exceeded", 429)
        assert second.requests == []


@pytest.mark.asyncio
async def test_http_concurrency_cannot_exceed_active_budget(tmp_path, keys, clock, monkeypatch):
    release = asyncio.Event()
    decided = asyncio.Event()
    mutex = threading.Lock()
    count = 0
    loop = asyncio.get_running_loop()

    async def handler(request):
        await release.wait()
        return provider_reply(request)

    async with open_gateway(tmp_path / "concurrent.db", keys, clock, handler=handler) as gateway:
        original = gateway.store.reserve

        def counted(*args):
            nonlocal count
            result = original(*args)
            with mutex:
                count += 1
                if count == 80:
                    loop.call_soon_threadsafe(decided.set)
            return result

        monkeypatch.setattr(gateway.store, "reserve", counted)
        tasks = [asyncio.create_task(gateway.client.post("/v1/complete", json={"prompt": "", "max_output_tokens": 1000}, headers=bearer(keys["a"]))) for _ in range(80)]
        await asyncio.wait_for(decided.wait(), timeout=15)
        assert gateway.store.usage(gateway.tenant(keys["a"])) == 50000
        release.set()
        responses = await asyncio.gather(*tasks)
        assert sum(response.status_code == 200 for response in responses) == 50
        assert sum(response.status_code == 429 for response in responses) == 30
        assert len(gateway.requests) == 50
        assert gateway.store.usage(gateway.tenant(keys["a"])) == 50


@pytest.mark.asyncio
async def test_cancel_during_admission_waits_for_commit_then_settles(gateway, keys, monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    original = gateway.store.reserve

    def slow_reserve(*args):
        entered.set()
        assert release.wait(timeout=5)
        return original(*args)

    monkeypatch.setattr(gateway.store, "reserve", slow_reserve)
    task = asyncio.create_task(gateway.client.post("/v1/complete", json={"prompt": "x", "max_output_tokens": 10}, headers=bearer(keys["a"])))
    assert await asyncio.to_thread(entered.wait, 2)
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert gateway.store.usage(gateway.tenant(keys["a"])) == 11
    with closing(sqlite3.connect(gateway.store.path)) as connection:
        assert connection.execute("SELECT state FROM reservations").fetchone()[0] == "settled"
    assert gateway.requests == []


@pytest.mark.asyncio
async def test_cancel_during_provider_closes_work_and_charges_full(tmp_path, keys, clock):
    started = asyncio.Event()
    closed = asyncio.Event()

    async def handler(request):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            closed.set()

    async with open_gateway(tmp_path / "quota.db", keys, clock, handler=handler) as gateway:
        task = asyncio.create_task(gateway.client.post("/v1/complete", json={"prompt": "x", "max_output_tokens": 10}, headers=bearer(keys["a"])))
        await asyncio.wait_for(started.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.wait_for(closed.wait(), timeout=2)
        assert gateway.store.usage(gateway.tenant(keys["a"])) == 11


@pytest.mark.asyncio
@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer tenant-a"}, {"Authorization": "Basic fake"}])
async def test_invalid_authentication_never_reaches_provider(gateway, headers):
    response = await gateway.client.post("/v1/complete", json={"prompt": "x"}, headers=headers)
    assert_public_error(response, "unauthorized", 401)
    assert response.headers["www-authenticate"] == "Bearer"
    assert gateway.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [b"bad json", b'{"prompt":7}', b'{"prompt":"x","tenant":"spoofed"}', b'{"prompt":"x","prompt":"y"}'])
async def test_invalid_body_never_reaches_provider(gateway, keys, body):
    response = await gateway.client.post("/v1/complete", content=body, headers=bearer(keys["a"]))
    assert_public_error(response, "invalid_request", 400)
    assert gateway.requests == []


@pytest.mark.asyncio
async def test_storage_failure_is_sanitized_and_fail_closed(gateway, keys, monkeypatch, caplog):
    def unavailable(*args):
        raise StoreUnavailable("SENSITIVE_DATABASE_PATH")

    monkeypatch.setattr(gateway.store, "reserve", unavailable)
    monkeypatch.setattr(gateway.store, "settle", unavailable)
    response = await gateway.client.post("/v1/complete", json={"prompt": "SENSITIVE_PROMPT"}, headers=bearer(keys["a"]))
    assert_public_error(response, "quota_unavailable", 503)
    assert gateway.requests == []
    assert "SENSITIVE" not in caplog.text and keys["a"] not in caplog.text


@pytest.mark.asyncio
async def test_cancel_after_reconciliation_commit_does_not_double_charge(gateway, keys, monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    original = gateway.store.settle

    def settling(request_id, actual=None):
        result = original(request_id, actual)
        if actual is not None:
            entered.set()
            assert release.wait(timeout=5)
        return result

    monkeypatch.setattr(gateway.store, "settle", settling)
    task = asyncio.create_task(gateway.client.post("/v1/complete", json={"prompt": "hello", "max_output_tokens": 10}, headers=bearer(keys["a"])))
    assert await asyncio.to_thread(entered.wait, 2)
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert gateway.store.usage(gateway.tenant(keys["a"])) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("content,headers", [
    (b'not json', {"Content-Type": "application/json"}),
    (b'{"text":7}', {"Content-Type": "application/json"}),
    (b'{"text":"ok","extra":"SENSITIVE"}', {"Content-Type": "application/json"}),
    (b'{"text":"ok"}', {"Content-Type": "text/plain"}),
    (b'{"text":"ok"}', {"Content-Type": "application/json", "Content-Encoding": "gzip"}),
    (b'x' * 300001, {"Content-Type": "application/json"}),
])
async def test_invalid_bounded_provider_payloads(tmp_path, keys, clock, content, headers):
    async with open_gateway(tmp_path / "quota.db", keys, clock, handler=lambda req: httpx.Response(200, content=content, headers=headers)) as gateway:
        response = await gateway.client.post("/v1/complete", json={"prompt": "x", "max_output_tokens": 5}, headers=bearer(keys["a"]))
        assert_public_error(response, "invalid_provider_response", 502)
        assert len(gateway.requests) == 1 and gateway.store.usage(gateway.tenant(keys["a"])) == 6
