import json

import pytest
from pydantic import ValidationError

from task_04_limiter.accounting import actual_usage, reservation_tokens
from task_04_limiter.auth import authenticate
from task_04_limiter.models import CompletionRequest, ProviderResult, Settings
from task_04_limiter.tokenization import count_tokens, encoding, truncate_to_tokens


def test_actual_token_ids_reservation_and_optional_usage():
    assert encoding().encode_ordinary("hello world") == [15339, 1917]
    assert count_tokens("hello world") == 2
    assert count_tokens("hello world") != len("hello world".encode("utf-8"))
    request = CompletionRequest(prompt="café", max_output_tokens=10)
    assert reservation_tokens(request) == 12
    assert actual_usage(request, ProviderResult(text="ok")).model_dump() == {"input_tokens": 2, "output_tokens": 1}


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
    {"text": "too long"}, {"text": "ok", "usage": {"input_tokens": 0, "output_tokens": 1}},
    {"text": "ok", "usage": {"input_tokens": 1, "output_tokens": 2}},
])
def test_inconsistent_or_excessive_usage_rejected(result):
    with pytest.raises(ValueError):
        actual_usage(CompletionRequest(prompt="x", max_output_tokens=1), ProviderResult(**result))


@pytest.mark.parametrize("text", ["hello world", "café", "こんにちは世界🙂", "<|endoftext|>", "🙂🙂 mixed text"])
def test_token_budget_truncation_is_unicode_safe(text):
    for budget in range(count_tokens(text) + 1):
        limited = truncate_to_tokens(text, budget)
        assert text.startswith(limited)
        assert "\ufffd" not in limited
        assert count_tokens(limited) <= budget
    assert truncate_to_tokens(text, count_tokens(text)) == text


def test_token_cap_is_not_a_byte_cap_and_special_spellings_are_ordinary_text():
    assert truncate_to_tokens("hello world", 1) == "hello"
    assert count_tokens("<|endoftext|>") == len(encoding().encode_ordinary("<|endoftext|>")) == 7


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
