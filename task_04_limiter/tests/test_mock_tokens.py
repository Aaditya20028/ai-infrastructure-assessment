import httpx
import pytest
import tiktoken

from task_04_limiter.mock_provider import create_mock_app


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["primary", "secondary"])
@pytest.mark.parametrize("maximum", [1, 2, 3, 4, 10])
async def test_both_providers_report_real_tokens_and_honor_output_token_limit(name, maximum):
    reference = tiktoken.get_encoding("cl100k_base")
    app = create_mock_app(name)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://mock") as client:
        response = await client.post("/v1/complete", json={"prompt": "hello world", "max_output_tokens": maximum})
    assert response.status_code == 200
    body = response.json()
    assert body["usage"]["input_tokens"] == len(reference.encode_ordinary("hello world")) == 2
    assert body["usage"]["output_tokens"] == len(reference.encode_ordinary(body["text"])) <= maximum
    if maximum == 1:
        assert body["text"] == "Mock"  # Four bytes, one real token.
