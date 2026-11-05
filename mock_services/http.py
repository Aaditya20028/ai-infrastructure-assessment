"""Deterministic HTTP provider fixtures; deliberately not a vendor API emulator."""

import asyncio
import json
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

app = FastAPI(title="Local mock providers")


class FixtureRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    scenario: str = Field(default="ok", pattern="^(ok|unavailable)$")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "mock"}


@app.post("/providers/{provider}/complete")
async def complete(provider: str, request: FixtureRequest) -> dict:
    if provider not in {"primary", "secondary"}:
        raise HTTPException(status_code=404, detail="Unknown fixture provider")
    if request.scenario == "unavailable":
        raise HTTPException(status_code=503, detail="Simulated provider failure")
    return {"provider": provider, "text": "Mock response", "usage": {"input_tokens": 4, "output_tokens": 2}}


@app.get("/stream")
async def stream() -> StreamingResponse:
    async def events() -> AsyncIterator[str]:
        # Synthetic PII is intentionally split across application events.
        # TCP may split or coalesce these further; tests must not assume TCP chunks.
        for chunk in ("Contact alice@", "example.test", " for details."):
            yield "data: " + json.dumps({"text": chunk}) + "\n\n"
            await asyncio.sleep(0)
        yield "data: [DONE]\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")
