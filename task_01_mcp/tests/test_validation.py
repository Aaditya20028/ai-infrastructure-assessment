import math

import pytest
from mcp.shared.exceptions import MCPError
from pydantic import ValidationError

from task_01_mcp import server
from task_01_mcp.models import CustomerLookup, RefundRequest


@pytest.mark.parametrize("customer_id", ["CUST-00001", "CUST-12345", "CUST-99999"])
def test_valid_customer_ids(customer_id):
    assert CustomerLookup(customer_id=customer_id).customer_id == customer_id


@pytest.mark.parametrize("customer_id", [
    "", "CUST-1234", "CUST-123456", "cust-12345", "CUST-12A45", " CUST-12345",
    "CUST-12345 ", "CUST-12345\n", "CUST-１２３４５", "CUST-١٢٣٤٥", 12345, True, None,
])
def test_invalid_customer_ids(customer_id):
    with pytest.raises(ValidationError):
        CustomerLookup(customer_id=customer_id)


@pytest.mark.parametrize("amount", [0, -1, -0.1, math.nan, math.inf, -math.inf, "1.5", True, None])
def test_invalid_amounts(amount):
    with pytest.raises(ValidationError):
        RefundRequest(customer_id="CUST-00001", amount=amount, reason="Valid reason")


@pytest.mark.parametrize("reason", ["", "123456789", 1234567890, None])
def test_invalid_reasons(reason):
    with pytest.raises(ValidationError):
        RefundRequest(customer_id="CUST-00001", amount=1.5, reason=reason)


@pytest.mark.parametrize("amount", [0.01, 1, 1.5, 1e100])
def test_positive_json_numbers(amount):
    # JSON has a number type: Pydantic strict float accepts integers, not bools.
    request = RefundRequest(customer_id="CUST-00001", amount=amount, reason="1234567890")
    assert request.amount == amount


def test_lookup_and_refund_are_deterministic_and_do_not_mutate_records():
    record = server.get_customer_record("CUST-00001")
    record["name"] = "Changed copy"
    assert server.get_customer_record("CUST-00001")["name"] == "Alex Example"
    first = server.trigger_refund("CUST-00001", 12.5, "Product damaged")
    assert first == server.trigger_refund("CUST-00001", 12.5, "Product damaged")
    assert first["status"] == "simulated" and first["mock"] is True


def test_missing_mock_customer_is_domain_result():
    assert server.get_customer_record("CUST-99999") == {"customer_id": "CUST-99999", "found": False}
    assert server.trigger_refund("CUST-99999", 1.5, "Product damaged")["status"] == "customer_not_found"


@pytest.mark.asyncio
async def test_unexpected_failure_is_sanitized_protocol_error(monkeypatch, caplog):
    def broken(**kwargs):
        raise RuntimeError("SENSITIVE_EXCEPTION_CONTENT")

    model, _, description = server._TOOLS["get_customer_record"]
    monkeypatch.setitem(server._TOOLS, "get_customer_record", (model, broken, description))
    with pytest.raises(MCPError) as error:
        await server.call_tool(None, server.StrictCallParams(name="get_customer_record", arguments={"customer_id": "CUST-00001"}))
    assert error.value.code == -32603
    assert error.value.message == "Internal server error"
    assert "SENSITIVE_EXCEPTION_CONTENT" not in caplog.text


@pytest.mark.asyncio
async def test_invalid_values_not_logged_or_reflected(caplog):
    with pytest.raises(MCPError) as error:
        await server.call_tool(None, server.StrictCallParams(name="get_customer_record", arguments={"customer_id": "SENSITIVE_INVALID_VALUE"}))
    assert error.value.code == -32602
    assert "SENSITIVE_INVALID_VALUE" not in str(error.value.error)
    assert "SENSITIVE_INVALID_VALUE" not in caplog.text


@pytest.mark.asyncio
async def test_request_boundary_sanitizes_non_tool_failures(caplog):
    async def broken(ctx):
        raise RuntimeError("SENSITIVE_NON_TOOL_FAILURE")

    with pytest.raises(MCPError) as error:
        await server.protocol_errors(None, broken)
    assert error.value.code == -32603
    assert error.value.message == "Internal server error"
    assert "SENSITIVE_NON_TOOL_FAILURE" not in caplog.text


@pytest.mark.asyncio
async def test_request_boundary_preserves_protocol_errors():
    async def invalid(ctx):
        raise MCPError(-32601, "Method not found")

    with pytest.raises(MCPError) as error:
        await server.protocol_errors(None, invalid)
    assert error.value.code == -32601
