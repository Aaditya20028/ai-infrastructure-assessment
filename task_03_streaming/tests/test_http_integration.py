import json
import time

import httpx
import pytest

from task_03_streaming.devtools import local_services
from task_03_streaming.mock_provider import NORMAL
from task_03_streaming.sse import SSEParser


@pytest.fixture(scope="module")
def services():
    with local_services(delay=0.025) as pair:
        yield pair


def read_events(response):
    parser = SSEParser()
    for chunk in response.iter_bytes():
        yield from parser.feed(chunk)
    parser.finish()


def test_actual_http_sse_redaction_and_first_output_before_completion(services):
    first_output = None
    text = []
    done = False
    started = time.perf_counter()
    with httpx.Client(timeout=10, trust_env=False) as client:
        with client.stream("POST", services["gateway"], json={"prompt": "demo"}) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            for event in read_events(response):
                assert event.event == "message"
                if event.data == "[DONE]":
                    done = True
                else:
                    part = json.loads(event.data)["choices"][0]["delta"]["content"]
                    if part and first_output is None:
                        first_output = time.perf_counter() - started
                    text.append(part)
    total = time.perf_counter() - started
    output = "".join(text)
    assert output == "Hello there. Email: [REDACTED]. SSN: [REDACTED]. Card: [REDACTED]. End. "
    assert done and 0 < first_output < total
    assert all(value not in output for value in ["alice@", "123-45", "4111"])
    assert all(value not in "".join(services["gateway_service"].logs) for value in ["alice@", "123-45", "4111"])


def test_actual_client_disconnect_and_subsequent_normal_stream(services):
    with httpx.Client(timeout=10, trust_env=False) as client:
        with client.stream("POST", services["gateway"], json={"prompt": "large"}) as response:
            first = next(read_events(response))
            assert first.event == "message"
            # Exit without waiting for the thousands of remaining deltas.
        with client.stream("POST", services["gateway"], json={"prompt": "normal"}) as response:
            parts = [json.loads(event.data)["choices"][0]["delta"]["content"]
                     for event in read_events(response) if event.data != "[DONE]"]
    assert "".join(parts) == "".join(NORMAL)
