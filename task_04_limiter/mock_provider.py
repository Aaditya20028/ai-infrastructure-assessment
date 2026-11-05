import asyncio
import math

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from .accounting import input_tokens
from .models import CompletionRequest
from .tokenization import count_tokens, encoding, truncate_to_tokens


def create_mock_app(name="primary", behavior="ok", delay=3.2):
    if name not in {"primary", "secondary"} or behavior not in {"ok", "rate_limit", "slow", "unavailable"} or not math.isfinite(delay) or delay < 0 or delay > 30:
        raise ValueError("Invalid mock provider settings")
    encoding()  # Load/cache vocabulary before accepting timed model requests.
    app = FastAPI(title="Local mock model provider", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.calls = []

    @app.post("/v1/complete")
    async def complete(request: CompletionRequest):
        app.state.calls.append(request)
        if behavior == "rate_limit":
            return JSONResponse({"error": "simulated_rate_limit"}, status_code=429)
        if behavior == "unavailable":
            return JSONResponse({"error": "simulated_unavailable"}, status_code=503)
        if behavior == "slow":
            await asyncio.sleep(delay)
        text = truncate_to_tokens("Mock " + name + " completion.", request.max_output_tokens)
        return {"text": text, "usage": {"input_tokens": input_tokens(request.prompt), "output_tokens": count_tokens(text)}}

    return app
