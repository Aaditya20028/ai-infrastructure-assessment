import json
import sys

import pytest

from .conftest import StdioPeer


def assert_error(response, code):
    assert "result" not in response
    assert response["error"]["code"] == code


def test_exact_tool_catalog_and_schemas(peer):
    response = peer.request("tools/list", {}, request_id="catalog-id")
    tools = {tool["name"]: tool for tool in response["result"]["tools"]}
    assert set(tools) == {"get_customer_record", "trigger_refund"}
    lookup = tools["get_customer_record"]["inputSchema"]
    refund = tools["trigger_refund"]["inputSchema"]
    assert lookup["properties"]["customer_id"]["pattern"] == r"^CUST-[0-9]{5}$"
    assert lookup["additionalProperties"] is False
    assert set(refund["required"]) == {"customer_id", "amount", "reason"}
    assert refund["properties"]["amount"]["exclusiveMinimum"] == 0
    assert refund["properties"]["reason"]["minLength"] == 10


def test_valid_lookup_and_zero_id(peer):
    response = peer.request("tools/call", {"name": "get_customer_record", "arguments": {"customer_id": "CUST-00001"}}, request_id=0)
    assert not response["result"].get("isError", False)
    record = json.loads(response["result"]["content"][0]["text"])
    assert record == {"customer_id": "CUST-00001", "name": "Alex Example", "found": True, "status": "active"}


def test_valid_refund(peer):
    params = {"name": "trigger_refund", "arguments": {"customer_id": "CUST-00001", "amount": 12.5, "reason": "Product damaged"}}
    first = peer.request("tools/call", params)["result"]
    second = peer.request("tools/call", params)["result"]
    assert first == second
    receipt = json.loads(first["content"][0]["text"])
    assert receipt["status"] == "simulated"
    assert receipt["amount"] == 12.5
    assert receipt["refund_id"].startswith("MOCK-")


@pytest.mark.parametrize("customer_id", ["", "cust-00001", "CUST-1234", "CUST-123456", "CUST-12X45", "CUST-１２３４５", "CUST-00001\n", 1, True, None])
def test_invalid_lookup_wire(peer, customer_id):
    assert_error(peer.request("tools/call", {"name": "get_customer_record", "arguments": {"customer_id": customer_id}}), -32602)


@pytest.mark.parametrize("arguments", [
    {}, {"customer_id": "CUST-00001"},
    {"customer_id": "BAD", "amount": 1.5, "reason": "Product damaged"},
    *[{"customer_id": "CUST-00001", "amount": value, "reason": "Product damaged"} for value in (0, -1, -0.1, "1.5", True, None)],
    {"customer_id": "CUST-00001", "amount": 1.5, "reason": "123456789"},
    {"customer_id": "CUST-00001", "amount": 1.5, "reason": 1234567890},
    {"customer_id": "CUST-00001", "amount": 1.5, "reason": "Product damaged", "extra": 1},
])
def test_invalid_refund_wire(peer, arguments):
    assert_error(peer.request("tools/call", {"name": "trigger_refund", "arguments": arguments}), -32602)


@pytest.mark.parametrize("params", [
    {}, {"name": "get_customer_record"}, {"name": "get_customer_record", "arguments": None},
    {"name": "get_customer_record", "arguments": []}, {"name": "get_customer_record", "arguments": "bad"},
    {"name": "get_customer_record", "arguments": {"customer_id": "CUST-00001", "extra": 1}},
    {"name": None}, {"name": 1}, [], "bad", 7,
])
def test_missing_and_malformed_params(peer, params):
    assert_error(peer.request("tools/call", params), -32602)


def test_absent_and_explicit_null_params(peer):
    assert_error(peer.request("tools/call"), -32602)
    peer.send({"jsonrpc": "2.0", "id": "null-params", "method": "tools/call", "params": None})
    response = peer.receive()
    assert response["id"] == "null-params"
    assert_error(response, -32602)


def test_unknown_tool_and_method(peer):
    assert_error(peer.request("tools/call", {"name": "unknown", "arguments": {}}), -32602)
    assert_error(peer.request("unknown/method", {}), -32601)


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_non_json_numeric_constants(peer, constant):
    peer.send_raw('{"jsonrpc":"2.0","id":"nonfinite","method":"tools/call","params":{"name":"trigger_refund","arguments":{"customer_id":"CUST-00001","amount":' + constant + ',"reason":"Product damaged"}}}')
    response = peer.receive()
    assert response["id"] is None
    assert_error(response, -32700)


def test_json_number_overflow_is_invalid_params(peer):
    peer.send_raw('{"jsonrpc":"2.0","id":"overflow","method":"tools/call","params":{"name":"trigger_refund","arguments":{"customer_id":"CUST-00001","amount":1e999,"reason":"Product damaged"}}}')
    response = peer.receive()
    assert response["id"] == "overflow"
    assert_error(response, -32602)


@pytest.mark.parametrize("frame,code,request_id", [
    ("{broken", -32700, None), ("null", -32600, None), ("[]", -32600, None),
    ('{"jsonrpc":"1.0","id":"bad-version","method":"tools/list"}', -32600, "bad-version"),
    ('{"jsonrpc":"2.0","id":true,"method":"tools/list"}', -32600, None),
    ('{"jsonrpc":"2.0","id":1.5,"method":"tools/list"}', -32600, None),
    ('{"jsonrpc":"2.0","id":null,"method":"tools/list"}', -32600, None),
    ('{"jsonrpc":"2.0","id":[],"method":"tools/list"}', -32600, None),
    ('{"jsonrpc":"2.0","id":"missing-method"}', -32600, "missing-method"),
])
def test_bad_frames_and_connection_recovery(peer, frame, code, request_id):
    peer.send_raw(frame)
    response = peer.receive()
    assert response["id"] == request_id
    assert_error(response, code)
    assert "result" in peer.request("tools/list", {})


def test_notifications_do_not_receive_responses(peer):
    peer.send({"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "unknown"}})
    peer.send({"jsonrpc": "2.0", "method": "tools/call", "params": []})
    assert "result" in peer.request("ping", {}, request_id="notification-barrier")


def test_pipelined_request_id_types(peer):
    for request_id in [42, "42", "", -7]:
        peer.send({"jsonrpc": "2.0", "id": request_id, "method": "tools/list"})
    received = [peer.receive() for _ in range(4)]
    assert {(type(item["id"]), item["id"]) for item in received} == {(int, 42), (str, "42"), (str, ""), (int, -7)}


def test_utf8_reason_is_not_corrupted(peer):
    reason = "Produit abîmé — remboursement"
    peer.send_raw(json.dumps({"jsonrpc": "2.0", "id": "unicode", "method": "tools/call", "params": {
        "name": "trigger_refund", "arguments": {"customer_id": "CUST-00001", "amount": 1.5, "reason": reason},
    }}, ensure_ascii=False))
    response = peer.receive()
    assert response["id"] == "unicode"
    assert json.loads(response["result"]["content"][0]["text"])["reason"] == reason


def test_stdout_isolation_and_unexpected_failure_on_real_wire():
    # Inject a test-only failing implementation, never a production backdoor.
    code = '''
from task_01_mcp.__main__ import isolate_stdout
wire = isolate_stdout()
import atexit, asyncio, logging, os, subprocess, sys
from task_01_mcp import server
logging.basicConfig(stream=sys.stderr, level=logging.INFO)
print("PYTHON_PRINT_NOISE", flush=True)
os.write(1, b"NATIVE_STDOUT_NOISE\\n")
subprocess.run([sys.executable, "-c", "print('CHILD_STDOUT_NOISE', flush=True)"], check=True)
atexit.register(lambda: print("EXIT_STDOUT_NOISE", flush=True))
def broken(**kwargs):
    print("HANDLER_STDOUT_NOISE", flush=True)
    raise RuntimeError("SENSITIVE_FAILURE_DETAIL")
model, _, description = server._TOOLS["get_customer_record"]
server._TOOLS["get_customer_record"] = (model, broken, description)
asyncio.run(server.serve(wire))
wire.close()
'''
    instance = StdioPeer([sys.executable, "-c", code])
    try:
        instance.initialize()
        response = instance.request("tools/call", {"name": "get_customer_record", "arguments": {"customer_id": "CUST-00001"}}, request_id="failure-id")
        assert_error(response, -32603)
        assert response["error"]["message"] == "Internal server error"
        assert "SENSITIVE_FAILURE_DETAIL" not in json.dumps(response)
        assert "result" in instance.request("tools/list", {})
    finally:
        instance.close()
    stderr = "".join(instance.stderr)
    for marker in ["PYTHON_PRINT_NOISE", "NATIVE_STDOUT_NOISE", "CHILD_STDOUT_NOISE", "HANDLER_STDOUT_NOISE", "EXIT_STDOUT_NOISE", "server starting", "Unexpected tool failure"]:
        assert marker in stderr
    assert "SENSITIVE_FAILURE_DETAIL" not in stderr
