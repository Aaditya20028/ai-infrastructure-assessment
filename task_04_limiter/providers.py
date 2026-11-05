"""Bounded HTTP provider calls and a strict, non-blocking deadline race."""

import asyncio
import time

import httpx

from .accounting import actual_usage
from .models import CompletionRequest, ProviderResult, parse_json

PRIMARY_TIMEOUT_SECONDS = 3.0


class ProviderError(Exception):
    def __init__(self, kind="failure", status=None):
        self.kind = kind
        self.status = status


class DeadlineExceeded(Exception):
    pass


class Deadlines:
    def __init__(self, clock=time.monotonic, waiter=asyncio.wait):
        self.clock = clock
        self.waiter = waiter
        self.inflight = set()

    def _finished(self, task):
        self.inflight.discard(task)
        if not task.cancelled():
            task.exception()  # Retrieve late errors without logging their values.

    async def run(self, coroutine, seconds):
        task = asyncio.create_task(coroutine)
        self.inflight.add(task)
        task.add_done_callback(self._finished)
        deadline = self.clock() + seconds
        try:
            while True:
                remaining = deadline - self.clock()
                if remaining <= 0:
                    raise DeadlineExceeded
                done, _ = await self.waiter({task}, timeout=remaining, return_when=asyncio.FIRST_COMPLETED)
                # A tie/late response loses. Never await cancellation cleanup
                # before starting fallback, unlike wait_for's cleanup delay.
                if self.clock() >= deadline:
                    raise DeadlineExceeded
                if task in done:
                    return task.result()
        finally:
            if not task.done():
                task.cancel()

    async def close(self):
        tasks = list(self.inflight)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.wait(tasks, timeout=1.0)


class ProviderClient:
    def __init__(self, client: httpx.AsyncClient):
        self.client = client

    async def complete(self, url, request: CompletionRequest) -> ProviderResult:
        response = None
        try:
            outgoing = httpx.Request("POST", str(url), json=request.model_dump(), headers={"Accept": "application/json", "Accept-Encoding": "identity"})
            response = await self.client.send(outgoing, stream=True)
            if response.status_code != 200:
                raise ProviderError("http", response.status_code)
            if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                raise ProviderError("invalid")
            if response.headers.get("content-encoding", "identity").lower() != "identity":
                raise ProviderError("invalid")
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > 300000:
                    raise ProviderError("invalid")
            result = ProviderResult.model_validate(parse_json(bytes(body)))
            actual_usage(request, result)
            return result
        except httpx.DecodingError:
            raise ProviderError("invalid") from None
        except httpx.TimeoutException:
            raise DeadlineExceeded from None
        except ProviderError:
            raise
        except (ValueError, RecursionError):
            raise ProviderError("invalid") from None
        except Exception:
            raise ProviderError("failure") from None
        finally:
            if response is not None:
                try:
                    await response.aclose()
                except Exception:
                    pass  # No exception text from a provider is public/logged.


class ModelRouter:
    def __init__(self, providers, settings, deadlines=None):
        self.providers = providers
        self.settings = settings
        self.deadlines = deadlines or Deadlines()

    async def complete(self, request):
        reason = None
        try:
            result = await self.deadlines.run(self.providers.complete(self.settings.primary_url, request), PRIMARY_TIMEOUT_SECONDS)
            return result, "primary", reason
        except DeadlineExceeded:
            reason = "primary_timeout"
        except ProviderError as exc:
            if exc.kind != "http" or exc.status != 429:
                raise
            reason = "primary_rate_limit"
        result = await self.deadlines.run(self.providers.complete(self.settings.secondary_url, request), self.settings.secondary_timeout)
        return result, "secondary", reason
