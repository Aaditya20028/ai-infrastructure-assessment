"""Authenticate -> reserve -> route -> reconcile exactly one logical request."""

import asyncio
from contextlib import asynccontextmanager
import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import httpx

from .accounting import actual_usage, reservation_tokens
from .auth import authenticate
from .models import CompletionRequest, Settings, parse_json
from .providers import DeadlineExceeded, ModelRouter, ProviderClient, ProviderError
from .storage import QuotaStore, StoreUnavailable, db_call

logger = logging.getLogger(__name__)


def error(code, message, status, request_id):
    return JSONResponse({"error": {"code": code, "message": message, "request_id": request_id}}, status_code=status,
                        headers={"WWW-Authenticate": "Bearer"} if status == 401 else None)


def create_app(settings=None, *, transport=None, store=None, deadlines=None):
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app):
        app.state.store = store if store is not None else await db_call(QuotaStore, settings.database)
        async with httpx.AsyncClient(transport=transport, timeout=None, trust_env=False, follow_redirects=False,
                                     limits=httpx.Limits(max_connections=20, max_keepalive_connections=10)) as client:
            router = ModelRouter(ProviderClient(client), settings, deadlines)
            app.state.router = router
            try:
                yield
            finally:
                await router.deadlines.close()

    app = FastAPI(title="SQLite LLM model router", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.post("/v1/complete")
    async def complete(request: Request):
        request_id = uuid.uuid4().hex
        tenant = authenticate(request.headers.getlist("authorization"), settings)
        if tenant is None:
            return error("unauthorized", "Valid tenant API key required", 401, request_id)
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 262144:
                return error("invalid_request", "Request too large", 413, request_id)
        try:
            generation = CompletionRequest.model_validate(parse_json(bytes(body)))
            reservation = reservation_tokens(generation)
        except (ValueError, TypeError, RecursionError):
            return error("invalid_request", "Invalid completion request", 400, request_id)
        reconciled = False
        try:
            if not await db_call(app.state.store.reserve, tenant, request_id, reservation):
                return error("quota_exceeded", "Token quota exceeded", 429, request_id)
            result, provider, fallback = await app.state.router.complete(generation)
            usage = actual_usage(generation, result)
            await db_call(app.state.store.settle, request_id, usage.input_tokens + usage.output_tokens)
            reconciled = True
            return JSONResponse({"request_id": request_id, "text": result.text, "provider": provider, "fallback_reason": fallback,
                                 "usage": {**usage.model_dump(), "total_tokens": usage.input_tokens + usage.output_tokens,
                                           "counting_method": "utf8_bytes_v1"}})
        except StoreUnavailable:
            return error("quota_unavailable", "Token quota temporarily unavailable", 503, request_id)
        except DeadlineExceeded:
            return error("provider_timeout", "Completion provider timed out", 504, request_id)
        except ProviderError as exc:
            if exc.kind == "http" and exc.status in (429, 503):
                return error("providers_unavailable", "Completion provider unavailable", 503, request_id)
            code = "invalid_provider_response" if exc.kind == "invalid" else "provider_error"
            return error(code, "Completion provider failed", 502, request_id)
        except Exception:
            logger.warning("Completion request failed")
            return error("gateway_error", "Completion could not be completed", 500, request_id)
        finally:
            if not reconciled:
                try:
                    # No-op for a denied/uncommitted admission or an already
                    # reconciled winner; failed/cancelled active work stays charged.
                    await db_call(app.state.store.settle, request_id)
                except StoreUnavailable:
                    logger.warning("Quota reconciliation deferred; reservation remains held")

    return app
