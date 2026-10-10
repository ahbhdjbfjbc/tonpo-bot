"""Pydantic schemas for API request/response and TradingView webhook."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Union
import math
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ── Auth ─────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    telegram_id: int
    api_key: Optional[str] = None
    # Development / bot-linked login: one-time code issued by Telegram bot
    login_code: Optional[str] = None


class TelegramWebAppLoginRequest(BaseModel):
    """Raw Telegram Web App initData; user identity is inside signed data."""
    init_data: str = Field(min_length=1, max_length=4096)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: Dict[str, Any]


# ── TradingView Signal ───────────────────────────────────────────────────────

class TradingViewSignalSchema(BaseModel):
    """Canonical schema for TradingView webhook payloads."""
    model_config = ConfigDict(extra="forbid")

    symbol: str
    action: str  # BUY / SELL
    entry: Optional[float] = None
    stop_loss: float
    take_profit: Optional[Union[float, List[float]]] = None
    take_profits: Optional[List[float]] = None
    timeframe: Optional[str] = None
    timestamp: Optional[Union[int, float, str]] = None
    strategy: Optional[str] = None
    source: Optional[str] = None
    id: Optional[str] = None
    signal_id: Optional[str] = None

    @field_validator("entry", "stop_loss", mode="before")
    @classmethod
    def finite_price(cls, v):
        if v is None:
            return v
        value = float(v)
        if not math.isfinite(value) or value <= 0:
            raise ValueError("price must be finite and positive")
        return value

    @field_validator("take_profit", "take_profits", mode="before")
    @classmethod
    def finite_targets(cls, v):
        if v is None:
            return v
        values = v if isinstance(v, list) else [v]
        parsed = [float(item) for item in values]
        if not parsed or any(not math.isfinite(item) or item <= 0 for item in parsed):
            raise ValueError("take profit must contain finite positive prices")
        return parsed if isinstance(v, list) else parsed[0]

    @field_validator("action")
    @classmethod
    def normalize_action(cls, v: str) -> str:
        a = str(v).upper().strip()
        if a not in {"BUY", "SELL"}:
            raise ValueError("action must be BUY or SELL")
        return a

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, v: str) -> str:
        s = str(v).upper().strip()
        if not s or len(s) > 32:
            raise ValueError("invalid symbol")
        return s

    def resolved_tps(self) -> List[float]:
        if self.take_profits:
            return [float(x) for x in self.take_profits]
        if self.take_profit is not None:
            if isinstance(self.take_profit, list):
                return [float(x) for x in self.take_profit]
            return [float(self.take_profit)]
        raise ValueError("take_profit or take_profits required")


# ── Dashboard / API responses ────────────────────────────────────────────────

class StatusResponse(BaseModel):
    status: str
    message: Optional[str] = None
    data: Optional[Dict[str, Any]] = None


class AccountMetrics(BaseModel):
    balance: Optional[float] = None
    equity: Optional[float] = None
    margin: Optional[float] = None
    free_margin: Optional[float] = None
    margin_level: Optional[float] = None
    currency: Optional[str] = None
    daily_pl: Optional[float] = None
    total_pl: Optional[float] = None
    win_rate: Optional[float] = None
    open_positions: int = 0
    connected: bool = False
    broker: Optional[str] = None
    last_heartbeat: Optional[str] = None
    error: Optional[str] = None
    dry_run: bool = True


class SignalOut(BaseModel):
    id: int
    source: str
    symbol: Optional[str] = None
    direction: Optional[str] = None
    entry: Optional[str] = None
    stop_loss: Optional[str] = None
    take_profits: Optional[List[str]] = None
    signal_text: str
    status: str
    created_at: Optional[str] = None
    rejection_reason: Optional[str] = None
    external_id: Optional[str] = None


class TradeOut(BaseModel):
    id: int
    symbol: str
    order_type: str
    entry_price: Optional[float] = None
    exit_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profits: Optional[List[float]] = None
    position_size: Optional[float] = None
    profit_loss: Optional[float] = None
    status: str
    executed_at: Optional[str] = None
    signal_text: Optional[str] = None


class RiskSettingsOut(BaseModel):
    risk_per_trade: float
    max_daily_loss: Optional[float] = None
    max_open_trades: Optional[int] = None
    allowed_symbols: Optional[List[str]] = None
    blocked_symbols: Optional[List[str]] = None
    max_spread: Optional[float] = None
    max_slippage: Optional[float] = None
    max_volatility: Optional[float] = None
    session_start_utc: Optional[str] = None
    session_end_utc: Optional[str] = None
    max_daily_loss: Optional[float] = None
    max_consecutive_losses: Optional[int] = None
    protection_enabled: bool = True
    dry_run: bool = True


class MT5StatusOut(BaseModel):
    connected: bool
    account: Optional[str] = None
    broker: Optional[str] = None
    balance: Optional[float] = None
    equity: Optional[float] = None
    margin: Optional[float] = None
    free_margin: Optional[float] = None
    last_heartbeat: Optional[str] = None
    errors: List[str] = Field(default_factory=list)


class EngineInstanceIn(BaseModel):
    """User-owned MetaDocker binding; the API key is write-only."""
    model_config = ConfigDict(extra="forbid")

    engine_instance_id: str = Field(min_length=1, max_length=128)
    endpoint: str = Field(min_length=8, max_length=255)
    account_reference: str = Field(min_length=1, max_length=100)
    api_key: str = Field(min_length=24, max_length=512)
    engine_version: Optional[str] = Field(None, max_length=64)

    @field_validator("engine_instance_id", "account_reference")
    @classmethod
    def safe_reference(cls, value: str) -> str:
        value = value.strip()
        if not value or any(char in value for char in "\r\n\t"):
            raise ValueError("invalid engine reference")
        return value

    @field_validator("endpoint")
    @classmethod
    def safe_endpoint(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("endpoint must be an HTTP(S) URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("endpoint must not contain credentials or query data")
        return value


class EngineInstanceOut(BaseModel):
    engine_instance_id: str
    provider: str
    endpoint: str
    account_reference: str
    engine_version: Optional[str] = None
    status: str
    provision_status: str
    is_active: bool
    last_health_at: Optional[str] = None
    last_session: Optional[int] = None
    dry_run: bool = True
    message: Optional[str] = None
