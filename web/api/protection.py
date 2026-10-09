"""Authenticated protection status; frontend never decides execution eligibility."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from database.models import AdminSetting
from services.news_protection import NewsProtectionService
from config.settings import settings
from web.deps import get_current_user, get_db

router = APIRouter(prefix="/api/protection", tags=["protection"])
@router.get("")
def protection(user=Depends(get_current_user), db: Session=Depends(get_db)):
    kill = db.query(AdminSetting).filter(AdminSetting.key.in_(["kill_switch", "emergency_stop"])).all()
    active = any(str(row.value).lower() == "true" for row in kill)
    news = NewsProtectionService().system_status()
    return {"kill_switch": {"active": active, "status": "ACTIVE" if active else "INACTIVE"}, "news": news, "dry_run": bool(getattr(settings, "TRADING_DRY_RUN", True))}
