from contextlib import closing
import json
import sqlite3
import time

import httpx
import pytest

from task_04_limiter.devtools import local_services


@pytest.mark.parametrize("behavior,provider,reason", [
    ("ok", "primary", None), ("rate_limit", "secondary", "primary_rate_limit"),
    ("slow", "secondary", "primary_timeout"),
])
def test_real_gateway_two_providers_and_disk_ledger(behavior, provider, reason):
    with local_services(behavior=behavior, delay=3.2) as services:
        with httpx.Client(timeout=10, trust_env=False) as client:
            started = time.perf_counter()
            response = client.post(services["url"], json={"prompt": "hello", "max_output_tokens": 50},
                                   headers={"Authorization": "Bearer " + services["token"]})
            elapsed = time.perf_counter() - started
        assert response.status_code == 200
        body = response.json()
        assert body["provider"] == provider and body["fallback_reason"] == reason
        assert provider in body["text"]
        if behavior == "slow":
            assert elapsed >= 3.0
        with closing(sqlite3.connect(services["database"])) as connection:
            rows = connection.execute("SELECT tenant,units,state FROM reservations").fetchall()
        assert len(rows) == 1 and len(rows[0][0]) == 64
        assert rows[0][1] == body["usage"]["total_tokens"] and rows[0][2] == "settled"
        assert all(services["token"] not in "".join(service.logs) for service in services["services"])


def test_real_both_unavailable_response_is_safe():
    with local_services(behavior="rate_limit", secondary_behavior="unavailable") as services:
        response = httpx.post(services["url"], json={"prompt": "private", "max_output_tokens": 5},
                              headers={"Authorization": "Bearer " + services["token"]}, timeout=10, trust_env=False)
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "providers_unavailable"
        for private in (services["token"], str(services["database"]), "Traceback", "http://", "private"):
            assert private not in response.text
