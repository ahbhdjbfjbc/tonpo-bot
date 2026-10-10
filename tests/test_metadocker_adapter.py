import time

import httpx
import pytest

from gateway_client.metadocker import (
    MetaDockerConnectionAdapter,
    MetaDockerError,
    MetaDockerUnknownExecution,
)


@pytest.fixture
def transport():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/account":
            return httpx.Response(
                200,
                json={
                    "login": 123,
                    "server": "Demo",
                    "balance": 1000,
                    "equity": 990,
                    "margin_free": 900,
                    "currency": "USD",
                    "leverage": 100,
                },
            )
        if request.url.path == "/symbols/EURUSD":
            return httpx.Response(
                200,
                json={
                    "volume_min": 0.01,
                    "volume_max": 10,
                    "volume_step": 0.01,
                    "trade_tick_size": 0.00001,
                    "trade_tick_value": 1.0,
                    "point": 0.00001,
                    "digits": 5,
                    "trade_mode": 4,
                },
            )
        if request.url.path == "/symbols/EURUSD/tick":
            return httpx.Response(
                200,
                json={"bid": 1.1, "ask": 1.1002, "time": time.time()},
            )
        if request.url.path == "/positions":
            return httpx.Response(200, json={"positions": [{"ticket": 777, "symbol": "EURUSD"}]})
        if request.url.path == "/orders/market":
            return httpx.Response(200, json={"retcode": 10009, "deal": 111, "order": 222})
        if request.url.path == "/orders/send":
            return httpx.Response(200, json={"retcode": 10009, "order": 333})
        return httpx.Response(404, json={"detail": "not found"})

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_maps_account_symbol_and_fresh_price(transport):
    client = httpx.AsyncClient(transport=transport, base_url="http://bridge", headers={"X-API-Key": "x"})
    adapter = MetaDockerConnectionAdapter("http://bridge", "x" * 24, 7, "engine-a", client=client)
    try:
        account = await adapter.get_account_information()
        constraints = await adapter.get_symbol_constraints("EURUSD")
        price = await adapter.get_symbol_price("EURUSD")
    finally:
        await adapter.close()

    assert account["login"] == 123
    assert constraints["tick_size"] == 0.00001
    assert constraints["volume_step"] == 0.01
    assert price == {"bid": 1.1, "ask": 1.1002}


@pytest.mark.asyncio
async def test_market_result_does_not_confuse_deal_or_order_with_position(transport):
    client = httpx.AsyncClient(transport=transport, base_url="http://bridge")
    adapter = MetaDockerConnectionAdapter("http://bridge", "x" * 24, 7, "engine-a", client=client)
    try:
        result = await adapter.create_market_buy_order("EURUSD", 0.01)
    finally:
        await adapter.close()

    assert result["success"] is True
    assert result["status"] == "accepted"
    assert result["deal_id"] == "111"
    assert result["order_id"] == "222"
    assert "orderId" not in result  # no position evidence, so execution stays unverified


@pytest.mark.asyncio
async def test_pending_order_exposes_order_id_separately(transport):
    client = httpx.AsyncClient(transport=transport, base_url="http://bridge")
    adapter = MetaDockerConnectionAdapter("http://bridge", "x" * 24, 7, "engine-a", client=client)
    try:
        result = await adapter.create_limit_buy_order("EURUSD", 0.01, 1.09)
    finally:
        await adapter.close()

    assert result["order_id"] == "333"
    assert result["orderId"] == "333"
    assert result["position_id"] is None


@pytest.mark.asyncio
async def test_mutation_timeout_is_not_retried():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("upstream timeout", request=request)

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://bridge"
    )
    adapter = MetaDockerConnectionAdapter("http://bridge", "x" * 24, 7, "engine-a", client=client)
    try:
        with pytest.raises(MetaDockerUnknownExecution):
            await adapter.create_market_buy_order("EURUSD", 0.01)
    finally:
        await adapter.close()


@pytest.mark.asyncio
async def test_incomplete_constraints_fail_closed(transport):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"volume_min": 0.01})

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://bridge"
    )
    adapter = MetaDockerConnectionAdapter("http://bridge", "x" * 24, 7, "engine-a", client=client)
    try:
        with pytest.raises(MetaDockerError):
            await adapter.get_symbol_constraints("EURUSD")
    finally:
        await adapter.close()
