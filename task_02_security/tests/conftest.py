from contextlib import asynccontextmanager
from dataclasses import dataclass
import secrets

import httpx
import pytest
import pytest_asyncio

from task_02_security.app import create_app
from task_02_security.config import Settings
from task_02_security.mock_downstream import create_mock_app


@pytest.fixture(scope="session")
def tokens():
    return {"admin": secrets.token_urlsafe(32), "viewer": secrets.token_urlsafe(32)}


def rpc(method="tools/call", name="get_status", request_id=1):
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": {"name": name, "arguments": {}} if method == "tools/call" else {}}


def bearer(token):
    return {"Authorization": "Bearer " + token}


class SpyTransport(httpx.AsyncBaseTransport):
    def __init__(self, inner):
        self.inner = inner
        self.requests = []

    async def handle_async_request(self, request):
        self.requests.append(request)
        return await self.inner.handle_async_request(request)

    async def aclose(self):
        await self.inner.aclose()


@dataclass
class Harness:
    client: httpx.AsyncClient
    spy: SpyTransport
    downstream: object
    settings: Settings


@asynccontextmanager
async def open_gateway(tokens, handler=None, **overrides):
    downstream = create_mock_app()
    transport = httpx.MockTransport(handler) if handler else httpx.ASGITransport(app=downstream)
    spy = SpyTransport(transport)
    settings = Settings(token_roles={token: role for role, token in tokens.items()}, **overrides)
    app = create_app(settings, transport=spy)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gateway") as client:
            yield Harness(client, spy, downstream, settings)


@pytest_asyncio.fixture
async def gateway(tokens):
    async with open_gateway(tokens) as harness:
        yield harness
