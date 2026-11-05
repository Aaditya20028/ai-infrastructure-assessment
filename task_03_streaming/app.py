"""HTTP streaming gateway. Never forward unvalidated upstream bytes."""

import asyncio
from contextlib import asynccontextmanager
import logging

import anyio
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
import httpx
from pydantic import ValidationError

from .models import DeltaEvent, GenerationRequest, Settings
from .redaction import Redactor
from .sse import DONE, ERROR, SSEParser, StreamFormatError, delta_frame

logger = logging.getLogger(__name__)


async def close_upstream(response):
    # Disconnect cancellation must not interrupt connection cleanup.
    with anyio.CancelScope(shield=True):
        with anyio.move_on_after(2):
            try:
                await response.aclose()
            except Exception:
                logger.warning("Provider connection cleanup failed")


async def filtered_stream(upstream: httpx.Response, settings: Settings):
    parser = SSEParser()
    redactor = Redactor()
    try:
        async with asyncio.timeout(settings.total_timeout):
            async for chunk in upstream.aiter_raw():
                if len(chunk) > 65536:
                    raise StreamFormatError("Network chunk limit exceeded")
                # Slice an available chunk; never wait to fill a fixed-size read.
                for offset in range(0, len(chunk), 4096):
                    for event in parser.feed(chunk[offset:offset + 4096]):
                        if event.event != "message":
                            raise StreamFormatError("Unsupported upstream event")
                        if event.data == "[DONE]":
                            tail = redactor.finish()
                            if tail:
                                yield delta_frame(tail)
                            yield DONE
                            return
                        delta = DeltaEvent.model_validate_json(event.data)
                        safe = redactor.feed(delta.choices[0].delta.content)
                        if safe:
                            yield delta_frame(safe)
            parser.finish()
            raise StreamFormatError("Missing completion event")
    except Exception:
        # On failure, discard all ambiguous suffixes. No unsafe final flush.
        logger.warning("Upstream stream rejected")
        yield ERROR
    finally:
        await close_upstream(upstream)


class ClosingStreamResponse(StreamingResponse):
    def __init__(self, iterator, upstream):
        super().__init__(iterator, media_type="text/event-stream", headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})
        self.upstream = upstream

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            with anyio.CancelScope(shield=True):
                with anyio.move_on_after(2):
                    await self.body_iterator.aclose()
            await close_upstream(self.upstream)


def create_app(settings: Settings | None = None, transport=None):
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app):
        async with httpx.AsyncClient(transport=transport, trust_env=False, follow_redirects=False,
                                     timeout=settings.idle_timeout, limits=httpx.Limits(max_connections=20, max_keepalive_connections=10)) as client:
            app.state.provider = client
            yield

    app = FastAPI(title="Streaming PII Gateway", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.post("/v1/generate")
    async def generate(request: Request):
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 16384:
                return JSONResponse({"error": "Request too large"}, status_code=413)
        try:
            generation = GenerationRequest.model_validate_json(bytes(body))
        except ValidationError:
            return JSONResponse({"error": "Invalid generation request"}, status_code=400)
        upstream = None
        try:
            outgoing = httpx.Request("POST", str(settings.provider_url), json=generation.model_dump(),
                                     headers={"Accept": "text/event-stream", "Accept-Encoding": "identity"})
            async with asyncio.timeout(settings.idle_timeout):
                upstream = await app.state.provider.send(outgoing, stream=True)
            if upstream.status_code != 200 or upstream.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "text/event-stream":
                raise StreamFormatError("Bad upstream response")
            if upstream.headers.get("content-encoding", "identity").lower() != "identity":
                raise StreamFormatError("Compressed upstream stream unsupported")
            return ClosingStreamResponse(filtered_stream(upstream, settings), upstream)
        except (TimeoutError, httpx.TimeoutException):
            if upstream is not None:
                await close_upstream(upstream)
            return JSONResponse({"error": "Provider timeout"}, status_code=504)
        except (ValueError, httpx.HTTPError):
            if upstream is not None:
                await close_upstream(upstream)
            return JSONResponse({"error": "Provider unavailable"}, status_code=502)
        except Exception:
            if upstream is not None:
                await close_upstream(upstream)
            logger.warning("Provider request failed")
            return JSONResponse({"error": "Provider unavailable"}, status_code=502)

    return app
