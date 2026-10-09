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
from services.subscription import SubscriptionService, TrialService
from services.results import ResultsService
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
        win_rate=round(user.win_rate, 1) if user.win_rate is not None else None,
        connected=bool(user.has_gateway_credentials and getattr(user, "mt_connected", False)),
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
            logger.info("Dashboard live metrics unavailable for user %s (%s)", user.id, type(exc).__name__)
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
            "rejection_reason": r.rejection_reason,
            "news_status": r.news_status,
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

    # Keep subscription state explicit without exposing payment or credential data.
    try:
        usage = SubscriptionService(db).get_usage_stats(user.telegram_id)
        subscription = {
            "plan": usage.get("plan", user.subscription_tier),
            "expiry": usage.get("expiry"),
            "trades_today": usage.get("trades_today", 0),
            "trade_limit": usage.get("trade_limit"),
            "remaining": max(0, (usage.get("trade_limit") or 0) - (usage.get("trades_today") or 0)),
            "features": usage.get("features", {}),
        }
    except Exception as exc:
        logger.info("Dashboard subscription state unavailable for user %s (%s)", user.id, type(exc).__name__)
        subscription = {
            "plan": user.subscription_tier,
            "expiry": user.subscription_expiry.isoformat() if user.subscription_expiry else None,
            "trades_today": getattr(user, "daily_trades", 0) or 0,
            "trade_limit": None,
            "remaining": None,
            "features": {},
        }

    if subscription["plan"] == "free":
        subscription["status"] = "FREE TRIAL" if getattr(user, "trial_end", None) else "FREE"
    elif subscription["expiry"]:
        subscription["status"] = "ACTIVE" if subscription["expiry"] > datetime.utcnow().isoformat() else "EXPIRED"
    else:
        subscription["status"] = "ACTIVE"

    activity = ResultsService(db).activity(user.telegram_id)
    trial_status = TrialService(db).get_trial_status(user.telegram_id)
    subscription["trial"] = trial_status
    subscription["available"] = subscription.get("status") not in {"EXPIRED", "INACTIVE"}
    subscription["plans"] = SubscriptionService(db).public_plan_catalog()
    engine_status = "dry_run" if bool(getattr(settings, "TRADING_DRY_RUN", True)) else "live_blocked_by_policy"
    signal_configured = bool(getattr(settings, "TRADINGVIEW_WEBHOOK_SECRET", None) and getattr(settings, "TRADINGVIEW_TELEGRAM_ID", None))
    onboarding = {
        "ready": bool(user.has_gateway_credentials and metrics.connected and subscription["available"] and getattr(user, "default_risk_factor", None) is not None),
        "steps": [
            {"key": "welcome", "label": "Welcome", "complete": True},
            {"key": "register", "label": "Register account", "complete": bool(user.is_active)},
            {"key": "mt5", "label": "Connect MT5", "complete": bool(user.has_gateway_credentials)},
            {"key": "verify_mt5", "label": "Verify MT5 connection", "complete": bool(metrics.connected)},
            {"key": "signal_flow", "label": "Understand TradingView signal flow", "complete": False, "action_required": "Review Signal Flow in the assistant"},
            {"key": "risk", "label": "Review risk settings", "complete": getattr(user, "default_risk_factor", None) is not None},
            {"key": "trial", "label": "Start 3-day free trial", "complete": bool(trial_status.get("active") or user.trial_used)},
            {"key": "dashboard", "label": "View dashboard", "complete": True},
            {"key": "signal_source", "label": "TradingView configuration", "complete": signal_configured, "action_required": "Configuration required" if not signal_configured else None},
            {"key": "dry_run", "label": "Start in DRY RUN", "complete": bool(getattr(settings, "TRADING_DRY_RUN", True))},
        ],
    }
    first_incomplete = next((index + 1 for index, step in enumerate(onboarding["steps"]) if not step["complete"]), len(onboarding["steps"]))
    onboarding["current_step"] = first_incomplete
    return {
        "account": metrics.model_dump(),
        "recent_trades": recent_trades,
        "recent_signals": recent_signals,
        "subscription": subscription,
        "activity": activity,
        "statuses": {
            "dry_run": bool(getattr(settings, "TRADING_DRY_RUN", True)),
            "mt5": "connected" if metrics.connected else "not_connected",
            "engine": engine_status,
        },
        "onboarding": onboarding,
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
        "trading_mode_badge": "🔵 DRY RUN",
    }
