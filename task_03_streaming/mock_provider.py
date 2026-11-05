"""Deterministic local provider. No paid API, real identity, or storage."""

import asyncio
import math

from fastapi import FastAPI
from fastapi.responses import StreamingResponse

from .models import GenerationRequest
from .sse import DONE, delta_frame

NORMAL = ("Hello there. ", "This is a normal ", "streaming response. ", "Café is open. ", "All done. ")
DEMO = ("Hello there. ", "Email: ", "alice@", "example.test", ". SSN: ", "123-", "45-", "6789",
        ". Card: ", "4111 ", "1111 ", "1111 ", "1111", ". End. ")


def create_mock_app(delay=0.01, repeats=2000):
    if not math.isfinite(delay) or delay < 0 or delay > 1 or not 1 <= repeats <= 100000:
        raise ValueError("Invalid mock settings")
    app = FastAPI(title="Mock streaming provider", docs_url=None, redoc_url=None, openapi_url=None)

    @app.post("/v1/generate")
    async def generate(request: GenerationRequest):
        async def events():
            parts = NORMAL if request.prompt in {"normal", "large"} else DEMO
            for _ in range(repeats if request.prompt == "large" else 1):
                for part in parts:
                    if delay:
                        await asyncio.sleep(delay)
                    frame = delta_frame(part)
                    # Real network chunks need not coincide with UTF-8/SSE/JSON.
                    for chunk in (frame[:3], frame[3:11], frame[11:]):
                        yield chunk
            yield DONE

        return StreamingResponse(events(), media_type="text/event-stream")

    return app
