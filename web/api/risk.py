"""Risk settings API."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from config.settings import settings
from database.models import User
from web.deps import get_current_user, get_db
from web.schemas import RiskSettingsOut

router = APIRouter(prefix="/api/risk", tags=["risk"])


@router.get("", response_model=RiskSettingsOut)
@router.get("/", response_model=RiskSettingsOut)
def get_risk(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    risk = float(getattr(user, "default_risk_factor", None) or settings.DEFAULT_RISK_FACTOR)
    us = user.settings
    return RiskSettingsOut(
        risk_per_trade=risk,
        max_daily_loss=getattr(us, "max_daily_loss", None) if us else None,
        max_open_trades=getattr(us, "max_open_trades", None) if us else None,
        allowed_symbols=user.allowed_symbols,
        blocked_symbols=user.blocked_symbols,
        max_spread=getattr(us, "max_spread", None) if us else None,
        max_slippage=getattr(us, "max_slippage", None) if us else None,
        max_volatility=getattr(us, "max_volatility", None) if us else None,
        session_start_utc=getattr(us, "session_start_utc", None) if us else None,
        session_end_utc=getattr(us, "session_end_utc", None) if us else None,
        max_consecutive_losses=getattr(us, "max_consecutive_losses", None) if us else None,
        protection_enabled=getattr(us, "protection_enabled", True) if us else True,
        dry_run=bool(getattr(settings, "TRADING_DRY_RUN", True)),
    )
