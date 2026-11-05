import asyncio
import json
import random

import httpx
import pytest

from task_03_streaming.app import ClosingStreamResponse, create_app, filtered_stream
from task_03_streaming.models import Settings
from task_03_streaming.sse import DONE, ERROR, SSEParser, delta_frame


class ProviderStream(httpx.AsyncByteStream):
    def __init__(self, parts, failure=None, block=False):
        self.parts = parts
        self.failure = failure
        self.block = block
        self.closed = False
        self.finished = False
        self.resume = asyncio.Event()
        self.waiting = asyncio.Event()

    async def __aiter__(self):
        for part in self.parts:
            yield part
        if self.block:
            self.waiting.set()
            await self.resume.wait()
        if self.failure:
            raise self.failure
        self.finished = True

    async def aclose(self):
        self.closed = True


def response_for(stream):
    return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, stream=stream)


def decode_output(frames):
    parser = SSEParser()
    text = []
    events = []
    for frame in frames:
        for event in parser.feed(frame):
            events.append(event)
            if event.event == "message" and event.data != "[DONE]":
                text.append(json.loads(event.data)["choices"][0]["delta"]["content"])
    parser.finish()
    return "".join(text), events


@pytest.mark.asyncio
async def test_end_to_end_randomized_sse_and_delta_boundaries(caplog):
    source = "Hello alice@example.test; SSN 123-45-6789; card 4111 1111 1111 1111. Café done."
    expected = "Hello [REDACTED]; SSN [REDACTED]; card [REDACTED]. Café done."
    for seed in range(30):
        rng = random.Random(seed)
        # One-character generation deltas AND unrelated network chunk splits.
        wire = b''.join(delta_frame(char) for char in source) + DONE
        parts = []
        offset = 0
        while offset < len(wire):
            width = rng.randint(1, 101)
            parts.append(wire[offset:offset + width])
            offset += width
        stream = ProviderStream(parts)
        result = [frame async for frame in filtered_stream(response_for(stream), Settings())]
        text, events = decode_output(result)
        assert text == expected and events[-1].data == "[DONE]" and stream.closed
    assert all(value not in caplog.text for value in ["alice@", "123-45", "4111"])


@pytest.mark.asyncio
async def test_stream_yields_before_upstream_finishes_and_backpressures():
    stream = ProviderStream([delta_frame("Hello there. "), delta_frame("Next words. "), DONE], block=True)
    output = filtered_stream(response_for(stream), Settings())
    first = await anext(output)
    assert decode_output([first])[0] == "Hello there. "
    assert not stream.finished
    await output.aclose()
    assert stream.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [
    b'data: not-json\n\n', b'data: {"choices":[]}\n\n',
    b'data: {"choices":[{"delta":{"content":7}}]}\n\n',
    b'data: {"choices":[{"delta":{"content":"x","extra":"alice@example.test"}}]}\n\n',
    b'event: error\ndata: SENSITIVE_ERROR\n\n', b'data: incomplete', b'\xff',
    b'data: ' + b'x' * 32769,
])
async def test_malformed_upstream_discards_ambiguous_suffix(bad, caplog):
    stream = ProviderStream([delta_frame("Safe words. alice@"), bad])
    frames = [frame async for frame in filtered_stream(response_for(stream), Settings())]
    text, events = decode_output(frames)
    assert text == "Safe words. "
    assert events[-1].event == "error" and DONE not in frames
    assert "alice@" not in b''.join(frames).decode() and "SENSITIVE_ERROR" not in caplog.text
    assert stream.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [httpx.ReadTimeout("SENSITIVE_DETAIL"), httpx.ReadError("SENSITIVE_DETAIL"), RuntimeError("SENSITIVE_DETAIL")])
async def test_upstream_stream_failures_are_sanitized(failure, caplog):
    stream = ProviderStream([delta_frame("Safe. alice@")], failure=failure)
    frames = [frame async for frame in filtered_stream(response_for(stream), Settings())]
    assert frames[-1] == ERROR and stream.closed
    assert "SENSITIVE_DETAIL" not in caplog.text and "alice@" not in b''.join(frames).decode()


@pytest.mark.asyncio
async def test_total_deadline_and_missing_done():
    for stream in [ProviderStream([delta_frame("alice@")], block=True), ProviderStream([delta_frame("alice@")])]:
        frames = [frame async for frame in filtered_stream(response_for(stream), Settings(total_timeout=0.02))]
        assert frames == [ERROR] and stream.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["a" * 513, "1 " * 65])
async def test_oversize_candidates_abort_without_leaking(text):
    stream = ProviderStream([delta_frame(text), DONE])
    frames = [frame async for frame in filtered_stream(response_for(stream), Settings())]
    assert frames == [ERROR] and stream.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("status,content_type,encoding", [(500, "text/event-stream", "identity"), (302, "text/event-stream", "identity"), (200, "text/html", "identity"), (200, "text/event-stream", "gzip")])
async def test_preflight_failures_are_http_errors(status, content_type, encoding):
    stream = ProviderStream([b"SENSITIVE_RAW_BODY"])

    def handler(request):
        assert "authorization" not in request.headers and "cookie" not in request.headers
        return httpx.Response(status, headers={"Content-Type": content_type, "Content-Encoding": encoding}, stream=stream)

    app = create_app(transport=httpx.MockTransport(handler))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gateway") as client:
            result = await client.post("/v1/generate", json={"prompt": "demo"}, headers={"Authorization": "Bearer sensitive", "Cookie": "private"})
    assert result.status_code == 502 and "SENSITIVE_RAW_BODY" not in result.text and stream.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("failure,status", [(httpx.ConnectTimeout("sensitive"), 504), (httpx.ConnectError("sensitive"), 502), (RuntimeError("sensitive"), 502)])
async def test_connection_failure_and_timeout(failure, status, caplog):
    def handler(request):
        raise failure

    app = create_app(transport=httpx.MockTransport(handler))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gateway") as client:
            result = await client.post("/v1/generate", json={"prompt": "demo"})
    assert result.status_code == status and "sensitive" not in result.text and "sensitive" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("body,status", [(b'not JSON', 400), (b'{"prompt":7}', 400), (b'{"prompt":"x","stream":false}', 400), (b'x' * 16385, 413)])
async def test_invalid_requests_do_not_reach_provider(body, status):
    def handler(request):
        pytest.fail("Invalid request forwarded")

    app = create_app(transport=httpx.MockTransport(handler))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gateway") as client:
            result = await client.post("/v1/generate", content=body)
    assert result.status_code == status


@pytest.mark.asyncio
@pytest.mark.parametrize("spec_version", ["2.0", "2.4"])
async def test_client_disconnect_closes_upstream(spec_version):
    stream = ProviderStream([delta_frame("Hello there. ")], block=True)
    upstream = response_for(stream)
    response = ClosingStreamResponse(filtered_stream(upstream, Settings()), upstream)
    delivered = asyncio.Event()

    async def receive():
        await delivered.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.body" and message.get("body"):
            delivered.set()
            if spec_version == "2.4":
                raise OSError("Client disconnected")

    from starlette.requests import ClientDisconnect
    try:
        await response({"type": "http", "asgi": {"spec_version": spec_version}}, receive, send)
    except ClientDisconnect:
        assert spec_version == "2.4"
    assert delivered.is_set() and stream.closed and not stream.finished


@pytest.mark.asyncio
async def test_cancelled_stream_task_closes_provider_without_error_frame():
    stream = ProviderStream([delta_frame("alice@")], block=True)
    output = filtered_stream(response_for(stream), Settings())
    pending = asyncio.create_task(anext(output))
    await asyncio.wait_for(stream.waiting.wait(), timeout=2)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert stream.closed
