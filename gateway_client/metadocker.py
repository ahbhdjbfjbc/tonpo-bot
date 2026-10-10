"""Safe MetaDocker adapter and durable per-user provider.

The adapter deliberately keeps MetaDocker's identifiers separate:
``order_id``, ``deal_id`` and ``position_id`` are never collapsed silently.
It does not retry trade mutations after a timeout because the broker may have
accepted the request already.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

import httpx

from services.auth import decrypt_gateway_api_key


class MetaDockerError(RuntimeError):
    """Safe, non-secret adapter error."""


class MetaDockerUnknownExecution(MetaDockerError):
    """The external result is ambiguous and requires reconciliation."""


@dataclass(frozen=True)
class MetaDockerTradeResult:
    status: str
    success: bool
    retcode: Optional[int]
    order_id: Optional[str]
    deal_id: Optional[str]
    position_id: Optional[str]
    raw: Dict[str, Any]

    def as_legacy_dict(self, *, legacy_id: str = "position") -> Dict[str, Any]:
        """Expose legacy fields without pretending IDs are interchangeable."""
        result: Dict[str, Any] = {
            "success": self.success,
            "status": self.status,
            "retcode": self.retcode,
            "order_id": self.order_id,
            "deal_id": self.deal_id,
            "position_id": self.position_id,
            "raw": self.raw,
        }
        # TradeExecutor historically uses orderId for the identifier it later
        # verifies. For market orders this must be a position ticket, not deal
        # or order. Missing position evidence therefore stays unknown.
        if legacy_id == "position" and self.position_id is not None:
            result["orderId"] = self.position_id
        elif legacy_id == "order" and self.order_id is not None:
            result["orderId"] = self.order_id
        return result


class MetaDockerConnectionAdapter:
    """Async adapter for one MetaDocker bridge / one MT5 account."""

    SUCCESS_RETCODE = 10009

    def __init__(
        self,
        base_url: str,
        api_key: str,
        user_id: int,
        engine_instance_id: str,
        *,
        timeout: float = 15.0,
        max_tick_age_seconds: float = 10.0,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        if not base_url or not base_url.startswith(("http://", "https://")):
            raise ValueError("MetaDocker endpoint must use http:// or https://")
        if not api_key:
            raise ValueError("MetaDocker API key is required")
        self.base_url = base_url.rstrip("/")
        self.user_id = user_id
        self.engine_instance_id = engine_instance_id
        self.max_tick_age_seconds = max_tick_age_seconds
        self._owns_client = client is None
        self.client = client or httpx.AsyncClient(
            base_url=self.base_url,
            headers={"X-API-Key": api_key},
            timeout=httpx.Timeout(timeout),
        )

    async def _request(self, method: str, path: str, *, mutation: bool = False, **kwargs: Any) -> Dict[str, Any]:
        try:
            response = await self.client.request(method, path, **kwargs)
        except httpx.TimeoutException as exc:
            if mutation:
                # Never retry mutations here. The caller must reconcile first.
                raise MetaDockerUnknownExecution("MetaDocker mutation timed out") from exc
            raise MetaDockerError("MetaDocker request timed out") from exc
        except httpx.RequestError as exc:
            raise MetaDockerError("MetaDocker connection failed") from exc
        if response.status_code >= 400:
            raise MetaDockerError(
                f"MetaDocker returned HTTP {response.status_code} for {method} {path}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise MetaDockerError("MetaDocker returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise MetaDockerError("MetaDocker returned an invalid response object")
        return payload

    async def health(self) -> Dict[str, Any]:
        return await self._request("GET", "/health")

    async def get_account_information(self) -> Dict[str, Any]:
        info = await self._request("GET", "/account")
        return {
            "login": info.get("login"),
            "server": info.get("server"),
            "balance": info.get("balance"),
            "equity": info.get("equity"),
            "margin": info.get("margin"),
            "free_margin": info.get("margin_free", info.get("free_margin")),
            "margin_level": info.get("margin_level"),
            "currency": info.get("currency"),
            "leverage": info.get("leverage"),
            "profit": info.get("profit"),
            "trade_allowed": info.get("trade_allowed"),
        }

    async def get_positions(self) -> List[Dict[str, Any]]:
        payload = await self._request("GET", "/positions")
        positions = payload.get("positions", [])
        if not isinstance(positions, list):
            raise MetaDockerError("MetaDocker positions response is invalid")
        return [
            {
                "id": p.get("ticket"),
                "position_id": p.get("ticket"),
                "symbol": p.get("symbol"),
                "type": p.get("type"),
                "volume": p.get("volume"),
                "openPrice": p.get("price_open"),
                "currentPrice": p.get("price_current"),
                "stopLoss": p.get("sl"),
                "takeProfit": p.get("tp"),
                "profit": p.get("profit"),
                "swap": p.get("swap"),
                "commission": p.get("commission"),
                "order_id": p.get("order"),
                "deal_id": p.get("deal"),
            }
            for p in positions
            if isinstance(p, dict)
        ]

    async def get_symbol_price(self, symbol: str) -> Dict[str, float]:
        tick = await self._request("GET", f"/symbols/{symbol}/tick")
        bid, ask = tick.get("bid"), tick.get("ask")
        if not isinstance(bid, (int, float)) or not isinstance(ask, (int, float)):
            raise MetaDockerError("MetaDocker returned no usable bid/ask")
        timestamp = tick.get("time_msc", tick.get("time"))
        if timestamp is None:
            raise MetaDockerError("MetaDocker returned a tick without timestamp")
        timestamp = float(timestamp)
        if timestamp > 1e12:
            timestamp /= 1000.0
        if time.time() - timestamp > self.max_tick_age_seconds:
            raise MetaDockerError("MetaDocker returned a stale tick")
        if not (0 < float(bid) < float(ask)):
            raise MetaDockerError("MetaDocker returned invalid bid/ask")
        return {"bid": float(bid), "ask": float(ask)}

    async def get_symbol_constraints(self, symbol: str) -> Dict[str, Any]:
        info = await self._request("GET", f"/symbols/{symbol}")

        def first(*keys: str) -> Any:
            for key in keys:
                if info.get(key) is not None:
                    return info[key]
            return None

        constraints = {
            "volume_min": first("volume_min"),
            "volume_max": first("volume_max"),
            "volume_step": first("volume_step"),
            "tick_size": first("tick_size", "trade_tick_size"),
            "tick_value": first("tick_value", "trade_tick_value"),
            "point": first("point"),
            "digits": first("digits"),
            "trade_mode": first("trade_mode"),
        }
        required = ("volume_min", "volume_max", "volume_step", "tick_size", "tick_value")
        if any(constraints[key] is None for key in required):
            raise MetaDockerError("MetaDocker symbol constraints are incomplete")
        return constraints

    def _trade_result(self, payload: Dict[str, Any]) -> MetaDockerTradeResult:
        retcode_raw = payload.get("retcode")
        try:
            retcode = int(retcode_raw) if retcode_raw is not None else None
        except (TypeError, ValueError):
            retcode = None
        order_id = _string_id(payload.get("order"))
        deal_id = _string_id(payload.get("deal"))
        position_id = _string_id(payload.get("position"))
        if retcode is None:
            return MetaDockerTradeResult("unknown", False, None, order_id, deal_id, position_id, payload)
        if retcode != self.SUCCESS_RETCODE:
            return MetaDockerTradeResult("rejected", False, retcode, order_id, deal_id, position_id, payload)
        return MetaDockerTradeResult("accepted", True, retcode, order_id, deal_id, position_id, payload)

    async def _mutate(self, path: str, body: Dict[str, Any], *, legacy_id: str = "position") -> Dict[str, Any]:
        payload = await self._request("POST", path, mutation=True, json=body)
        return self._trade_result(payload).as_legacy_dict(legacy_id=legacy_id)

    async def create_market_buy_order(self, symbol: str, volume: float, sl=None, tp=None, comment=None, magic=None):
        return await self._mutate("/orders/market", _market_body(symbol, "buy", volume, sl, tp, comment, magic))

    async def create_market_sell_order(self, symbol: str, volume: float, sl=None, tp=None, comment=None, magic=None):
        return await self._mutate("/orders/market", _market_body(symbol, "sell", volume, sl, tp, comment, magic))

    async def create_limit_buy_order(self, symbol: str, volume: float, price: float, sl=None, tp=None, comment=None, magic=None):
        return await self._pending(symbol, volume, price, 2, sl, tp, comment, magic)

    async def create_limit_sell_order(self, symbol: str, volume: float, price: float, sl=None, tp=None, comment=None, magic=None):
        return await self._pending(symbol, volume, price, 3, sl, tp, comment, magic)

    async def create_stop_buy_order(self, symbol: str, volume: float, price: float, sl=None, tp=None, comment=None, magic=None):
        return await self._pending(symbol, volume, price, 4, sl, tp, comment, magic)

    async def create_stop_sell_order(self, symbol: str, volume: float, price: float, sl=None, tp=None, comment=None, magic=None):
        return await self._pending(symbol, volume, price, 5, sl, tp, comment, magic)

    async def _pending(self, symbol, volume, price, order_type, sl, tp, comment, magic):
        body = {
            "action": 5,
            "symbol": symbol,
            "volume": volume,
            "price": price,
            "type": order_type,
        }
        _optional(body, "sl", sl)
        _optional(body, "tp", tp)
        _optional(body, "comment", comment)
        _optional(body, "magic", magic)
        return await self._mutate("/orders/send", body, legacy_id="order")

    async def verify_market_execution(self, position_id: str) -> bool:
        if not position_id:
            return False
        positions = await self.get_positions()
        return any(str(p.get("position_id")) == str(position_id) for p in positions)

    async def close_position(self, position_id: str) -> bool:
        payload = await self._request("POST", f"/positions/{int(position_id)}/close", mutation=True)
        result = self._trade_result(payload)
        return result.success and result.retcode == self.SUCCESS_RETCODE

    async def modify_position(self, position_id: str, sl=None, tp=None) -> bool:
        body = {"action": 6, "position": int(position_id)}
        _optional(body, "sl", sl)
        _optional(body, "tp", tp)
        payload = await self._request("POST", "/orders/send", mutation=True, json=body)
        result = self._trade_result(payload)
        return result.success and result.retcode == self.SUCCESS_RETCODE

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()


def _string_id(value: Any) -> Optional[str]:
    return str(value) if value is not None else None


def _optional(target: Dict[str, Any], key: str, value: Any) -> None:
    if value is not None:
        target[key] = value


def _market_body(symbol, side, volume, sl, tp, comment, magic):
    body = {"symbol": symbol, "side": side, "volume": volume}
    _optional(body, "sl", sl)
    _optional(body, "tp", tp)
    _optional(body, "comment", comment)
    _optional(body, "magic", magic)
    return body


class MetaDockerExecutionProvider:
    """Resolve each user to an active EngineInstance from the database."""

    provider_name = "metadocker"

    def __init__(self, session_factory: Callable[[], Any], *, timeout: float = 15.0):
        self.session_factory = session_factory
        self.timeout = timeout
        self.connections: Dict[str, MetaDockerConnectionAdapter] = {}
        self._connection_fingerprints: Dict[str, tuple[str, str]] = {}

    async def get_connection(self, telegram_id: int) -> MetaDockerConnectionAdapter:
        from database.repositories import EngineInstanceRepository

        db = self.session_factory()
        try:
            row = EngineInstanceRepository(db).get_active_for_telegram_id(telegram_id)
            if row is None:
                raise MetaDockerError("No active MetaDocker engine for user")
            key = decrypt_gateway_api_key(row.api_key_ciphertext)
            cached = self.connections.get(row.engine_instance_id)
            fingerprint = (row.endpoint, row.api_key_ciphertext)
            if cached is not None and self._connection_fingerprints.get(row.engine_instance_id) == fingerprint:
                return cached
            if cached is not None:
                await cached.close()
                self.connections.pop(row.engine_instance_id, None)
                self._connection_fingerprints.pop(row.engine_instance_id, None)
            connection = MetaDockerConnectionAdapter(
                row.endpoint,
                key,
                row.user_id,
                row.engine_instance_id,
                timeout=self.timeout,
            )
            self.connections[row.engine_instance_id] = connection
            self._connection_fingerprints[row.engine_instance_id] = fingerprint
            return connection
        finally:
            db.close()

    async def invalidate_engine(self, engine_instance_id: str) -> None:
        connection = self.connections.pop(engine_instance_id, None)
        self._connection_fingerprints.pop(engine_instance_id, None)
        if connection is not None:
            await connection.close()

    async def shutdown(self) -> None:
        for connection in list(self.connections.values()):
            await connection.close()
        self.connections.clear()
        self._connection_fingerprints.clear()
