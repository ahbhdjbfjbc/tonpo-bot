"""Pydantic schemas for API request/response and TradingView webhook."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field, field_validator


# ── Auth ─────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    telegram_id: int
    api_key: Optional[str] = None
    # Development / bot-linked login: one-time code issued by Telegram bot
    login_code: Optional[str] = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: Dict[str, Any]


# ── TradingView Signal ───────────────────────────────────────────────────────

class TradingViewSignalSchema(BaseModel):
    """Canonical schema for TradingView webhook payloads."""
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
    user_id: int  # target telegram user id

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
    dry_run: bool = True
    message: Optional[str] = None
