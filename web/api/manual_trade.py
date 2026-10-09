"""Manual execution request — ownership + pipeline + TRADING_DRY_RUN only."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from config.settings import settings
from database.models import SignalReceipt, User
from web.deps import get_current_user, get_db
from web.runtime import get_signal_pipeline

router = APIRouter(prefix="/api/signals", tags=["manual-trade"])


@router.post("/{receipt_id}/manual-execute")
async def manual_execute(
    receipt_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    receipt = (
        db.query(SignalReceipt)
        .filter(SignalReceipt.id == receipt_id, SignalReceipt.user_id == user.id)
        .first()
    )
    if not receipt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Signal not found")

    pipeline = get_signal_pipeline(db)
    if pipeline is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Signal pipeline not available",
        )
    if hasattr(pipeline, "confirm"):
        result = await pipeline.confirm(user.telegram_id, receipt_id)
    else:
        result = {"success": False, "status": "unavailable", "error": "Confirm path unavailable"}
    if isinstance(result, dict):
        result["dry_run"] = bool(getattr(settings, "TRADING_DRY_RUN", True))
        result["receipt_id"] = receipt_id
    return result
