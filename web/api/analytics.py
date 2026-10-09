"""Authenticated real-data Smart Analytics API."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from services.smart_analytics import SmartAnalyticsService
from web.deps import get_current_user, get_db

router = APIRouter(prefix="/api/analytics", tags=["analytics"])
@router.get("")
def analytics(period: str = Query("30d", pattern="^(today|7d|30d|all)$"), symbol: str | None = None, direction: str | None = None, status: str | None = None, rejection_reason: str | None = None, user=Depends(get_current_user), db: Session=Depends(get_db)):
    return SmartAnalyticsService(db).summary(user.telegram_id, period, symbol, direction, status, rejection_reason)
