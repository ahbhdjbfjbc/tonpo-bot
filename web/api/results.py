"""Authenticated Results Center, daily activity, and news status APIs."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from services.news_protection import NewsProtectionService
from services.results import ResultsService
from web.deps import get_current_user, get_db

router = APIRouter(prefix="/api", tags=["results"])


@router.get("/results")
def results(
    period: str = Query("30d", pattern="^(today|7d|30d|all)$"),
    user=Depends(get_current_user), db: Session = Depends(get_db),
):
    return ResultsService(db).results(user.telegram_id, period)


@router.get("/activity/today")
def activity(user=Depends(get_current_user), db: Session = Depends(get_db)):
    return ResultsService(db).activity(user.telegram_id)


@router.get("/news/status")
def news_status(user=Depends(get_current_user)):
    result = NewsProtectionService().system_status()
    return {
        "status": result["status"],
        "reason": result["reason"],
        "events": result.get("events", []),
        "next_event": result.get("next_event"),
        "protection_until": result.get("protection_until"),
        "provider": result.get("provider", "Trading Economics"),
        "last_update": result.get("last_update"),
        "enabled": NewsProtectionService().enabled,
        "blocks_new_trades": result["status"] in {"active", "unavailable", "stale"},
    }
