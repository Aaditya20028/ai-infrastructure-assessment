"""Explicit environment configuration; there are no built-in valid tokens."""

import os
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from .protocol import load_json

Role = Literal["admin", "viewer"]


class Settings(BaseModel):
    model_config = ConfigDict(strict=True, hide_input_in_errors=True, validate_default=True)
    token_roles: dict[str, Role] = Field(repr=False, min_length=1)
    upstream_url: HttpUrl = "http://127.0.0.1:8083/mcp"
    timeout_seconds: float = Field(default=5.0, gt=0, le=120, allow_inf_nan=False)
    max_request_bytes: int = Field(default=65536, gt=0)
    max_response_bytes: int = Field(default=1048576, gt=0)

    @field_validator("token_roles")
    @classmethod
    def validate_tokens(cls, tokens):
        if any(re.fullmatch(r"[A-Za-z0-9_-]{32,}", token) is None for token in tokens):
            raise ValueError("Mock tokens must be at least 32 URL-safe ASCII characters")
        return tokens

    @field_validator("upstream_url")
    @classmethod
    def validate_upstream(cls, url):
        if url.username or url.password or url.query or url.fragment:
            raise ValueError("Downstream URL cannot contain credentials, query, or fragment")
        return url

    @classmethod
    def from_env(cls):
        try:
            return cls(
                token_roles=load_json(os.environ["TASK2_TOKEN_ROLES"].encode()),
                upstream_url=os.environ.get("TASK2_UPSTREAM_URL", "http://127.0.0.1:8083/mcp"),
                timeout_seconds=float(os.environ.get("TASK2_TIMEOUT_SECONDS", "5")),
                max_request_bytes=int(os.environ.get("TASK2_MAX_REQUEST_BYTES", "65536")),
                max_response_bytes=int(os.environ.get("TASK2_MAX_RESPONSE_BYTES", "1048576")),
            )
        except (KeyError, ValueError, TypeError, RecursionError):
            raise RuntimeError("Invalid Task 2 configuration; set valid TASK2_TOKEN_ROLES and gateway settings") from None
