"""Strict public/provider contracts and explicit local configuration."""

import json
import os
from pathlib import Path
import re

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True)


class CompletionRequest(StrictModel):
    prompt: str = Field(max_length=50000)
    max_output_tokens: int = Field(default=256, ge=1, le=50000)


class Usage(StrictModel):
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)


class ProviderResult(StrictModel):
    text: str = Field(max_length=50000)
    usage: Usage | None = None


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON member")
        result[key] = value
    return result


def parse_json(body):
    def invalid(value):
        raise ValueError("Non-JSON constant")
    return json.loads(body, object_pairs_hook=unique_object, parse_constant=invalid)


class Settings(BaseModel):
    model_config = ConfigDict(validate_default=True, hide_input_in_errors=True)
    api_keys: dict[str, str] = Field(repr=False, min_length=1)
    database: Path = Path("data/task4_quota.sqlite3")
    primary_url: HttpUrl = "http://127.0.0.1:8087/v1/complete"
    secondary_url: HttpUrl = "http://127.0.0.1:8088/v1/complete"
    secondary_timeout: float = Field(default=3.0, gt=0, le=30, allow_inf_nan=False)

    @field_validator("api_keys")
    @classmethod
    def validate_keys(cls, values):
        if any(re.fullmatch(r"[A-Za-z0-9_-]{32,}", key) is None or re.fullmatch(r"[A-Za-z0-9_-]{1,64}", tenant) is None
               for key, tenant in values.items()):
            raise ValueError("Invalid API key or tenant configuration")
        return values

    @field_validator("database")
    @classmethod
    def disk_database(cls, path):
        if str(path) == ":memory:" or str(path).startswith("file:"):
            raise ValueError("An on-disk database path is required")
        return path

    @field_validator("primary_url", "secondary_url")
    @classmethod
    def safe_url(cls, url):
        if url.username or url.password or url.query or url.fragment:
            raise ValueError("Provider URLs cannot contain credentials, query, or fragment")
        return url

    @classmethod
    def from_env(cls):
        try:
            return cls(api_keys=parse_json(os.environ["TASK4_API_KEYS"]),
                       database=os.environ.get("TASK4_DATABASE", "data/task4_quota.sqlite3"),
                       primary_url=os.environ.get("TASK4_PRIMARY_URL", "http://127.0.0.1:8087/v1/complete"),
                       secondary_url=os.environ.get("TASK4_SECONDARY_URL", "http://127.0.0.1:8088/v1/complete"),
                       secondary_timeout=os.environ.get("TASK4_SECONDARY_TIMEOUT", "3"))
        except (ValueError, TypeError, KeyError, RecursionError):
            raise RuntimeError("Invalid Task 4 configuration") from None
