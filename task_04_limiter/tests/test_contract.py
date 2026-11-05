import json

import pytest
from pydantic import ValidationError

from task_04_limiter.accounting import actual_usage, reservation_tokens
from task_04_limiter.auth import authenticate
from task_04_limiter.models import CompletionRequest, ProviderResult, Settings


def test_utf8_byte_reservation_and_optional_usage():
    request = CompletionRequest(prompt="café", max_output_tokens=10)
    assert reservation_tokens(request) == 15
    assert actual_usage(request, ProviderResult(text="ok")).model_dump() == {"input_tokens": 5, "output_tokens": 2}


@pytest.mark.parametrize("body", [
    {"prompt": 1}, {"prompt": "x", "max_output_tokens": 0},
    {"prompt": "x", "max_output_tokens": -1}, {"prompt": "x", "max_output_tokens": 50001},
    {"prompt": "x", "max_output_tokens": True}, {"prompt": "x", "max_output_tokens": "5"},
    {"prompt": "x", "tenant": "admin"}, {},
])
def test_strict_request_validation(body):
    with pytest.raises(ValidationError):
        CompletionRequest(**body)


@pytest.mark.parametrize("result", [
    {"text": "too long"}, {"text": "ok", "usage": {"input_tokens": 0, "output_tokens": 2}},
    {"text": "ok", "usage": {"input_tokens": 1, "output_tokens": 1}},
])
def test_inconsistent_or_excessive_usage_rejected(result):
    with pytest.raises(ValueError):
        actual_usage(CompletionRequest(prompt="x", max_output_tokens=2), ProviderResult(**result))


def test_verified_keys_aliases_and_untrusted_claims(keys):
    settings = Settings(api_keys={keys["a"]: "tenant", keys["b"]: "tenant"})
    tenant = authenticate(["Bearer " + keys["a"]], settings)
    assert tenant == authenticate(["Bearer " + keys["b"]], settings)
    assert len(tenant) == 64 and tenant not in (keys["a"], keys["b"], "tenant")
    assert all(key not in repr(settings) for key in keys.values())
    for headers in ([], ["Bearer tenant"], ["Basic key"], ["Bearer a b"], ["Bearer é"], ["Bearer " + keys["a"], "Bearer " + keys["b"]]):
        assert authenticate(headers, settings) is None


@pytest.mark.parametrize("changes", [
    {"api_keys": {}}, {"api_keys": {"short": "tenant"}},
    {"database": ":memory:"}, {"primary_url": "file:///tmp/provider"},
    {"primary_url": "http://user@localhost/model"}, {"secondary_url": "http://localhost/?secret=bad"},
    {"secondary_timeout": 0}, {"secondary_timeout": float("inf")},
])
def test_invalid_configuration(keys, changes):
    with pytest.raises(ValidationError):
        Settings(**{"api_keys": {keys["a"]: "tenant"}, **changes})


def test_environment_requires_valid_mock_credentials(monkeypatch, keys):
    monkeypatch.delenv("TASK4_API_KEYS", raising=False)
    with pytest.raises(RuntimeError, match="Invalid Task 4 configuration"):
        Settings.from_env()
    monkeypatch.setenv("TASK4_API_KEYS", json.dumps({keys["a"]: "tenant-a"}))
    assert Settings.from_env().api_keys[keys["a"]] == "tenant-a"
