"""Per-user trading mode: demo | live. Independent of TRADING_DRY_RUN env barrier."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from config.settings import settings
from database.models import User, UserAuditLog
from web.deps import get_current_user, get_db

router = APIRouter(prefix="/api/trading-mode", tags=["trading-mode"])

ALLOWED = {"demo", "live"}


class ModeUpdate(BaseModel):
    mode: str = Field(..., description="demo or live")
    confirm_live: bool = Field(False, description="Required true when switching to live")


def _normalize(mode: str | None) -> str:
    m = (mode or "demo").strip().lower()
    return m if m in ALLOWED else "demo"


@router.get("")
@router.get("/")
def get_trading_mode(user: User = Depends(get_current_user)):
    mode = _normalize(getattr(user, "trading_mode", None))
    dry = bool(getattr(settings, "TRADING_DRY_RUN", True))
    return {
        "mode": mode,
        "label": "LIVE TRADING" if mode == "live" else "DEMO TRADING",
        "badge": "🟢 LIVE TRADING" if mode == "live" else "🔵 DEMO TRADING",
        "dry_run_env": dry,
        "real_orders_possible": bool(mode == "live" and not dry),
        "note": (
            "Environment TRADING_DRY_RUN blocks real broker orders regardless of user mode."
            if dry
            else "User mode live may send real orders when dry-run is off."
        ),
    }


@router.patch("")
@router.patch("/")
def set_trading_mode(
    body: ModeUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    new_mode = _normalize(body.mode)
    if body.mode.strip().lower() not in ALLOWED:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="mode must be demo or live")

    old = _normalize(getattr(user, "trading_mode", None))
    if new_mode == old:
        return get_trading_mode(user)

    # DEMO → LIVE requires explicit confirmation
    if new_mode == "live" and not body.confirm_live:
        # Audit failed attempt
        db.add(
            UserAuditLog(
                user_id=user.id,
                telegram_id=user.telegram_id,
                action="trading_mode_change",
                old_value={"mode": old},
                new_value={"mode": new_mode},
                source="web",
                result="rejected",
                failure_reason="confirm_live required",
            )
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Switching to LIVE requires confirm_live=true. LIVE may send real orders when the environment allows.",
        )

    user.trading_mode = new_mode
    db.add(
        UserAuditLog(
            user_id=user.id,
            telegram_id=user.telegram_id,
            action="trading_mode_change",
            old_value={"mode": old},
            new_value={"mode": new_mode},
            source="web",
            result="ok",
        )
    )
    db.commit()
    db.refresh(user)
    return get_trading_mode(user)
