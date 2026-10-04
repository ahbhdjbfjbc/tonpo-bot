"""User dashboard API — account metrics, recent activity."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from config.settings import settings
# trading_mode exposed per user
from database.models import SignalReceipt, Trade, User
from web.deps import get_current_user, get_db
from web.schemas import AccountMetrics

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def _safe_float(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


@router.get("")
@router.get("/")
async def dashboard_summary(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Aggregate account + activity snapshot for the user dashboard."""
    metrics = AccountMetrics(
        total_pl=_safe_float(getattr(user, "total_profit", None)),
        win_rate=round(user.win_rate, 1) if user.win_rate is not None else 0.0,
        connected=bool(user.has_gateway_credentials),
        dry_run=bool(getattr(settings, "TRADING_DRY_RUN", True)),
    )

    # Live MT5 metrics require GatewayManager (wired by the bot runtime).
    # When the web process runs standalone, surface honest "Not connected".
    if user.has_gateway_credentials:
        try:
            from web.runtime import get_gateway_connection
            connection = await get_gateway_connection(user)
            if connection is None:
                metrics.connected = False
                metrics.error = "Not connected"
            else:
                info = await connection.get_account_information()
                metrics.balance = _safe_float(info.get("balance"))
                metrics.equity = _safe_float(info.get("equity"))
                metrics.margin = _safe_float(info.get("margin"))
                metrics.free_margin = _safe_float(info.get("free_margin"))
                metrics.margin_level = _safe_float(info.get("margin_level"))
                metrics.currency = info.get("currency")
                metrics.broker = info.get("server")
                metrics.connected = True
                metrics.last_heartbeat = datetime.utcnow().isoformat() + "Z"
                positions = await connection.get_positions()
                metrics.open_positions = len(positions) if positions else 0
        except Exception as exc:
            metrics.connected = False
            metrics.error = "Not connected"
            logger.info("Dashboard live metrics unavailable for user %s: %s", user.id, str(exc)[:200])
    else:
        metrics.error = "Not connected"
        metrics.connected = False

    # Recent trades
    trades = (
        db.query(Trade)
        .filter(Trade.user_id == user.id)
        .order_by(Trade.created_at.desc())
        .limit(10)
        .all()
    )
    recent_trades = []
    for t in trades:
        recent_trades.append({
            "id": t.id,
            "symbol": t.symbol,
            "order_type": t.order_type,
            "entry_price": t.entry_price,
            "position_size": t.position_size,
            "profit_loss": getattr(t, "profit_loss", None),
            "status": t.status,
            "executed_at": t.executed_at.isoformat() + "Z" if t.executed_at else None,
            "created_at": t.created_at.isoformat() + "Z" if t.created_at else None,
        })

    # Recent signals
    receipts = (
        db.query(SignalReceipt)
        .filter(SignalReceipt.user_id == user.id)
        .order_by(SignalReceipt.created_at.desc())
        .limit(10)
        .all()
    )
    recent_signals = []
    for r in receipts:
        recent_signals.append({
            "id": r.id,
            "source": r.source,
            "signal_text": r.signal_text,
            "status": r.status,
            "created_at": r.created_at.isoformat() + "Z" if r.created_at else None,
        })

    # Daily P/L approximation from today's closed trades
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    day_trades = (
        db.query(Trade)
        .filter(Trade.user_id == user.id, Trade.created_at >= today_start)
        .all()
    )
    daily_pl = 0.0
    for t in day_trades:
        pl = getattr(t, "profit_loss", None)
        if pl is not None:
            daily_pl += float(pl)
    metrics.daily_pl = daily_pl

    return {
        "account": metrics.model_dump(),
        "recent_trades": recent_trades,
        "recent_signals": recent_signals,
        "dry_run": bool(getattr(settings, "TRADING_DRY_RUN", True)),
        "user": {
            "id": user.id,
            "telegram_id": user.telegram_id,
            "username": user.telegram_username,
            "subscription_tier": user.subscription_tier,
            "has_gateway": user.has_gateway_credentials,
            "trading_mode": (getattr(user, "trading_mode", None) or "demo"),
        },
        "trading_mode": (getattr(user, "trading_mode", None) or "demo"),
        "trading_mode_badge": (
            "🟢 LIVE TRADING" if (getattr(user, "trading_mode", None) or "demo") == "live"
            else "🔵 DEMO TRADING"
        ),
    }
