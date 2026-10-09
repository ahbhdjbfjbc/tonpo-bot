import asyncio

import pytest

from gateway_client.test_gateway import TestGateway


@pytest.mark.parametrize("state", ["accepted", "rejected", "partial", "filled", "timeout", "unknown"])
def test_local_gateway_exposes_explicit_simulated_states(state):
    gateway = TestGateway(state)
    result = asyncio.run(gateway.submit({"symbol": "EURUSD"}))
    assert result["status"] == state
    assert result["simulated"] is True
    assert len(gateway.submissions) == 1
    if state == "unknown":
        assert result["reconciliation_required"] is True


def test_local_gateway_reconciliation_is_explicit_and_not_a_fill_claim():
    gateway = TestGateway("unknown")
    result = asyncio.run(gateway.submit({"symbol": "EURUSD"}))
    assert result["status"] == "unknown"
    gateway.set_reconciliation("manual-order", "filled")
    reconciliation = asyncio.run(gateway.reconcile("manual-order"))
    assert reconciliation == {
        "success": True,
        "status": "filled",
        "order_id": "manual-order",
        "simulated": True,
        "reconciliation_required": False,
    }
