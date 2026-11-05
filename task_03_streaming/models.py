import os

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator
from typing import Literal


class StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True)


class GenerationRequest(StrictModel):
    prompt: str = Field(max_length=2048)
    stream: Literal[True] = True


class Delta(StrictModel):
    content: str = Field(max_length=8192)


class Choice(StrictModel):
    delta: Delta


class DeltaEvent(StrictModel):
    choices: list[Choice] = Field(min_length=1, max_length=1)


class Settings(BaseModel):
    model_config = ConfigDict(validate_default=True, hide_input_in_errors=True)
    provider_url: HttpUrl = "http://127.0.0.1:8085/v1/generate"
    idle_timeout: float = Field(default=5.0, gt=0, le=120, allow_inf_nan=False)
    total_timeout: float = Field(default=30.0, gt=0, le=300, allow_inf_nan=False)

    @field_validator("provider_url")
    @classmethod
    def safe_url(cls, url):
        if url.username or url.password or url.query or url.fragment:
            raise ValueError("Provider URL cannot contain credentials, query, or fragment")
        return url

    @classmethod
    def from_env(cls):
        try:
            return cls(provider_url=os.environ.get("TASK3_PROVIDER_URL", "http://127.0.0.1:8085/v1/generate"),
                       idle_timeout=os.environ.get("TASK3_IDLE_TIMEOUT", "5"),
                       total_timeout=os.environ.get("TASK3_TOTAL_TIMEOUT", "30"))
        except ValueError:
            raise RuntimeError("Invalid Task 3 configuration") from None
