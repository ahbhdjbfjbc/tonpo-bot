"""MT5 connection status API."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from config.settings import settings
from database.models import ConnectionLog, EngineInstance, User
from database.repositories import EngineInstanceRepository
from services.auth import encrypt_gateway_api_key
from web.deps import get_current_user, get_db
from web.schemas import EngineInstanceIn, EngineInstanceOut, MT5StatusOut

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/mt5", tags=["mt5"])


def _engine_out(row: EngineInstance) -> EngineInstanceOut:
    return EngineInstanceOut(
        engine_instance_id=row.engine_instance_id,
        provider=row.provider,
        endpoint=row.endpoint,
        account_reference=row.account_reference,
        engine_version=row.engine_version,
        status=row.status,
        provision_status=row.provision_status,
        is_active=bool(row.is_active),
        last_health_at=row.last_health_at.isoformat() if row.last_health_at else None,
        last_session=row.last_session,
    )


@router.get("/engines", response_model=List[EngineInstanceOut])
def list_engines(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """List only the caller's engine metadata; never return API keys."""
    rows = EngineInstanceRepository(db).list_for_user(user.id)
    return [_engine_out(row) for row in rows]


@router.put("/engine", response_model=EngineInstanceOut)
def bind_engine(
    payload: EngineInstanceIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Bind one MetaDocker instance to this user/account, encrypted at rest."""
    try:
        row = EngineInstanceRepository(db).upsert_for_user(
            user.id,
            engine_instance_id=payload.engine_instance_id,
            endpoint=payload.endpoint,
            account_reference=payload.account_reference,
            api_key_ciphertext=encrypt_gateway_api_key(payload.api_key) or "",
            engine_version=payload.engine_version,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _engine_out(row)


@router.delete("/engine/{engine_instance_id}")
def disable_engine(
    engine_instance_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Disable routing to an engine without deleting its audit record."""
    if not EngineInstanceRepository(db).disable_for_user(user.id, engine_instance_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Engine not found")
    return {"disabled": True, "engine_instance_id": engine_instance_id}


@router.get("/status", response_model=MT5StatusOut)
async def mt5_status(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    dry = bool(getattr(settings, "TRADING_DRY_RUN", True))
    errors: List[str] = []
    try:
        from web.runtime import get_gateway_connection
        connection = await get_gateway_connection(user)
        if connection is None:
            return MT5StatusOut(
                connected=False,
                dry_run=dry,
                message="Not connected — no active engine binding",
                errors=["No active MT5 engine is configured for this user"],
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
