"""User settings API."""
from __future__ import annotations

from typing import Any, Dict, Optional, List
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from config.settings import settings
from database.models import User
from web.deps import get_current_user, get_db
from services.subscription import SubscriptionService

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsUpdate(BaseModel):
    default_risk_factor: Optional[float] = Field(None, ge=0.001, le=0.1)
    language: Optional[str] = None
    notifications_enabled: Optional[bool] = None
    allowed_symbols: Optional[List[str]] = None
    blocked_symbols: Optional[List[str]] = None


@router.get("")
@router.get("/")
def get_settings(user: User = Depends(get_current_user)):
    us = user.settings
    return {
        "default_risk_factor": user.default_risk_factor,
        "language": getattr(user, "language", "ar"),
        "subscription_tier": user.subscription_tier,
        "allowed_symbols": user.allowed_symbols,
        "blocked_symbols": user.blocked_symbols,
        "has_gateway": user.has_gateway_credentials,
        "api_enabled": bool(us and getattr(us, "api_enabled", False)),
        "notifications_enabled": bool(us and getattr(us, "notifications_enabled", True)) if us else True,
        "dry_run": bool(getattr(settings, "TRADING_DRY_RUN", True)),
        "trading_dry_run": bool(getattr(settings, "TRADING_DRY_RUN", True)),
    }


@router.patch("")
@router.patch("/")
def update_settings(
    body: SettingsUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if body.default_risk_factor is not None:
        user.default_risk_factor = body.default_risk_factor
    if body.language is not None:
        if hasattr(user, "language"):
            user.language = body.language
    if body.notifications_enabled is not None and user.settings:
        if hasattr(user.settings, "notifications_enabled"):
            user.settings.notifications_enabled = body.notifications_enabled
    if body.allowed_symbols is not None:
        symbols = sorted({str(symbol).strip().upper() for symbol in body.allowed_symbols if str(symbol).strip()})
        if any(not re.fullmatch(r"[A-Z0-9._-]{2,20}", symbol) for symbol in symbols):
            raise HTTPException(status_code=422, detail="Invalid symbol format")
        plan = SubscriptionService(db).get_user_plan(user.telegram_id)
        if plan.max_symbols and len(symbols) > plan.max_symbols:
            raise HTTPException(status_code=403, detail="Symbol limit reached for your subscription")
        user.allowed_symbols = symbols
    if body.blocked_symbols is not None:
        symbols = sorted({str(symbol).strip().upper() for symbol in body.blocked_symbols if str(symbol).strip()})
        if any(not re.fullmatch(r"[A-Z0-9._-]{2,20}", symbol) for symbol in symbols):
            raise HTTPException(status_code=422, detail="Invalid symbol format")
        user.blocked_symbols = symbols
    db.commit()
    db.refresh(user)
    return {"status": "ok", "default_risk_factor": user.default_risk_factor}
