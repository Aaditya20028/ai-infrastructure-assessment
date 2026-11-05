import httpx
import pytest

from mock_services.http import app


@pytest.fixture
def transport():
    return httpx.ASGITransport(app=app)


@pytest.mark.asyncio
async def test_provider_scenarios(transport):
    async with httpx.AsyncClient(transport=transport, base_url="http://mock") as client:
        for provider in ("primary", "secondary"):
            response = await client.post(f"/providers/{provider}/complete", json={})
            assert response.status_code == 200
            assert response.json()["provider"] == provider
            assert response.json()["usage"] == {"input_tokens": 4, "output_tokens": 2}
        response = await client.post("/providers/primary/complete", json={"scenario": "unavailable"})
        assert response.status_code == 503
        response = await client.post("/providers/unknown/complete", json={})
        assert response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{"scenario": 1}, {"scenario": "other"}, {"extra": True}])
async def test_fixture_rejects_invalid_requests(transport, payload):
    async with httpx.AsyncClient(transport=transport, base_url="http://mock") as client:
        response = await client.post("/providers/primary/complete", json=payload)
        assert response.status_code == 422


@pytest.mark.asyncio
async def test_sse_fixture(transport):
    async with httpx.AsyncClient(transport=transport, base_url="http://mock") as client:
        response = await client.get("/stream")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert 'alice@' in response.text
        assert response.text.endswith("data: [DONE]\n\n")
        assert response.text.count("data: ") == 4
