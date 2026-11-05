from contextlib import asynccontextmanager
from dataclasses import dataclass
import json
import secrets

import httpx
import pytest
import pytest_asyncio

from task_04_limiter.app import create_app
from task_04_limiter.auth import authenticate
from task_04_limiter.models import Settings
from task_04_limiter.storage import QuotaStore


class Clock:
    def __init__(self, now=100.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture(scope="session")
def keys():
    return {"a": secrets.token_urlsafe(32), "b": secrets.token_urlsafe(32)}


def bearer(key):
    return {"Authorization": "Bearer " + key}


def provider_reply(request, text="ok", usage=True):
    payload = json.loads(request.content)
    body = {"text": text}
    if usage:
        body["usage"] = {"input_tokens": len(payload["prompt"].encode()), "output_tokens": len(text.encode())}
    return httpx.Response(200, json=body)


@dataclass
class Harness:
    client: httpx.AsyncClient
    store: QuotaStore
    settings: Settings
    requests: list

    def tenant(self, key):
        return authenticate(["Bearer " + key], self.settings)


@asynccontextmanager
async def open_gateway(path, keys, clock, handler=None, deadlines=None):
    requests = []

    async def spy(request):
        requests.append(request)
        if handler is None:
            return provider_reply(request)
        response = handler(request)
        return await response if hasattr(response, "__await__") else response

    settings = Settings(api_keys={keys["a"]: "tenant-a", keys["b"]: "tenant-b"}, database=path,
                        primary_url="http://primary/v1/complete", secondary_url="http://secondary/v1/complete")
    store = QuotaStore(path, clock=clock)
    app = create_app(settings, transport=httpx.MockTransport(spy), store=store, deadlines=deadlines)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gateway") as client:
            yield Harness(client, store, settings, requests)


@pytest_asyncio.fixture
async def gateway(tmp_path, keys, clock):
    async with open_gateway(tmp_path / "quota.sqlite3", keys, clock) as result:
        yield result
