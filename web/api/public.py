"""Read-only public information for unauthenticated visitors."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from config.settings import settings
from services.subscription import SubscriptionService
from web.deps import get_db

router = APIRouter(prefix="/api/public", tags=["public"])


@router.get("/catalog")
def public_catalog(db: Session = Depends(get_db)):
    """Expose active, visible plan metadata without user or payment data."""
    return {
        "bot_username": getattr(settings, "BOT_USERNAME", None),
        "plans": SubscriptionService(db).public_plan_catalog(),
    }


@router.get("/overview")
def public_overview(db: Session = Depends(get_db)):
    """Return only non-user-specific data needed by the original dashboard shell."""
    return {
        "public": True,
        "dry_run": bool(getattr(settings, "TRADING_DRY_RUN", True)),
        "user": None,
        "account": {"connected": False},
        "activity": {"has_data": False},
        "statuses": {"engine": "dry_run"},
        "subscription": {"plan": None, "status": "PUBLIC PREVIEW", "available": False, "trial": {"active": False}, "plans": SubscriptionService(db).public_plan_catalog()},
        "onboarding": {"ready": False, "steps": [
            {"key": "account", "label": "إنشاء حساب Tonpo", "complete": False},
            {"key": "mt5", "label": "ربط حساب MT5", "complete": False},
            {"key": "signal_source", "label": "إعداد مصدر الإشارات", "complete": False},
        ]},
        "recent_signals": [], "recent_trades": [],
    }
