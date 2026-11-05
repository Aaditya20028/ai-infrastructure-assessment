"""One bounded asynchronous request, with no retries or credential forwarding."""

import asyncio

import httpx

from .config import Settings
from .protocol import validate_response


class DownstreamFailure(Exception):
    pass


class DownstreamTimeout(Exception):
    pass


class Forwarder:
    def __init__(self, client: httpx.AsyncClient, settings: Settings):
        self.client = client
        self.settings = settings

    async def forward(self, body: bytes, request_id) -> bytes:
        try:
            async with asyncio.timeout(self.settings.timeout_seconds):
                # Construct directly: never merge the shared client's cookies
                # into another caller's request, even after a Set-Cookie reply.
                request = httpx.Request(
                    "POST", str(self.settings.upstream_url), content=body,
                    headers={"Content-Type": "application/json", "Accept": "application/json", "Accept-Encoding": "identity"},
                )
                response = await self.client.send(request, stream=True, follow_redirects=False)
                try:
                    if response.status_code != 200 or response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                        raise DownstreamFailure
                    chunks = bytearray()
                    async for chunk in response.aiter_bytes():
                        chunks.extend(chunk)
                        if len(chunks) > self.settings.max_response_bytes:
                            raise DownstreamFailure
                    data = bytes(chunks)
                    validate_response(data, request_id)
                    return data
                finally:
                    await response.aclose()
        except (TimeoutError, httpx.TimeoutException):
            raise DownstreamTimeout from None
        except (httpx.HTTPError, ValueError, RecursionError):
            raise DownstreamFailure from None
