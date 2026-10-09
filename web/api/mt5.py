"""MT5 connection status API."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from config.settings import settings
from database.models import ConnectionLog, User
from web.deps import get_current_user, get_db
from web.schemas import MT5StatusOut

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/mt5", tags=["mt5"])


@router.get("/status", response_model=MT5StatusOut)
async def mt5_status(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    dry = bool(getattr(settings, "TRADING_DRY_RUN", True))
    if not user.has_gateway_credentials:
        return MT5StatusOut(
            connected=False,
            dry_run=dry,
            message="Not connected — no gateway credentials",
            errors=["Gateway credentials not configured"],
        )

    errors: List[str] = []
    try:
        from web.runtime import get_gateway_connection
        connection = await get_gateway_connection(user)
        if connection is None:
            return MT5StatusOut(
                connected=False,
                dry_run=dry,
                message="Not connected — gateway session unavailable",
                errors=["Gateway connection not available in this process"],
            )
        info = await connection.get_account_information()
        return MT5StatusOut(
            connected=True,
            account=str(info.get("login")) if info.get("login") is not None else None,
            broker=info.get("server"),
            balance=float(info["balance"]) if info.get("balance") is not None else None,
            equity=float(info["equity"]) if info.get("equity") is not None else None,
            margin=float(info["margin"]) if info.get("margin") is not None else None,
            free_margin=float(info["free_margin"]) if info.get("free_margin") is not None else None,
            last_heartbeat=datetime.utcnow().isoformat() + "Z",
            dry_run=dry,
            message="Connected" + (" (DRY RUN — no live orders)" if dry else ""),
        )
    except Exception as exc:
        logger.info("MT5 status check failed for user %s (%s)", user.id, type(exc).__name__)
        errors.append("Gateway status unavailable")
        return MT5StatusOut(
            connected=False,
            dry_run=dry,
            message="Not connected",
            errors=errors,
        )


@router.get("/logs")
def connection_logs(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(ConnectionLog)
        .filter(ConnectionLog.user_id == user.id)
        .order_by(ConnectionLog.created_at.desc())
        .limit(50)
        .all()
    )
    return {
        "items": [
            {
                "id": r.id,
                "event": getattr(r, "event", None) or getattr(r, "status", None),
                "message": getattr(r, "message", None) or getattr(r, "details", None),
                "created_at": r.created_at.isoformat() + "Z" if r.created_at else None,
            }
            for r in rows
        ]
    }
