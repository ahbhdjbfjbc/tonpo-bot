"""MT5 connection status API."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, List
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from config.settings import settings
from database.models import ConnectionLog, EngineInstance, SubscriptionPlan, User
from database.repositories import EngineInstanceRepository
from services.auth import encrypt_gateway_api_key
from gateway_client.metadocker import MetaDockerConnectionAdapter, MetaDockerError
from web.deps import get_current_user, get_db
from web.schemas import EngineInstanceIn, EngineInstanceOut, MT5StatusOut

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/mt5", tags=["mt5"])


def _validate_engine_endpoint(endpoint: str) -> None:
    """Allow only operator-allowlisted MetaDocker destinations (SSRF boundary)."""
    parsed = urlsplit(endpoint)
    host = (parsed.hostname or "").lower().rstrip(".")
    allowed = {
        item.strip().lower().rstrip(".")
        for item in str(getattr(settings, "METADOCKER_ALLOWED_HOSTS", "")).split(",")
        if item.strip()
    }
    if not host:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Engine endpoint host is required")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Engine endpoint must not include credentials, query, or fragment",
        )
    if bool(getattr(settings, "METADOCKER_REQUIRE_HTTPS", True)) and parsed.scheme != "https":
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Engine endpoint must use HTTPS")
    if host in allowed:
        return
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail="Engine endpoint host is not allowlisted; configure METADOCKER_ALLOWED_HOSTS",
    )


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


def _connection_limit(user: User, db: Session) -> int:
    """Read the connection entitlement without committing the caller's transaction."""
    now = datetime.utcnow()
    snapshot = user.subscription_features if isinstance(user.subscription_features, dict) else {}
    if user.subscription_expiry and user.subscription_expiry >= now and "max_connections" in snapshot:
        return max(0, int(snapshot.get("max_connections") or 0))
    tier = "free" if user.subscription_expiry and user.subscription_expiry < now else user.subscription_tier
    plan = db.query(SubscriptionPlan).filter_by(tier=tier).first()
    if plan is None and tier != "free":
        plan = db.query(SubscriptionPlan).filter_by(tier="free").first()
    return max(0, int(plan.max_connections or 0)) if plan else 0


@router.get("/engines", response_model=List[EngineInstanceOut])
def list_engines(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """List only the caller's engine metadata; never return API keys."""
    rows = EngineInstanceRepository(db).list_for_user(user.id)
    return [_engine_out(row) for row in rows]


@router.put("/engine", response_model=EngineInstanceOut)
async def bind_engine(
    payload: EngineInstanceIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Bind one MetaDocker instance to this user/account, encrypted at rest."""
    _validate_engine_endpoint(payload.endpoint)
    repository = EngineInstanceRepository(db)
    connection = MetaDockerConnectionAdapter(
        payload.endpoint,
        payload.api_key,
        user.id,
        payload.engine_instance_id,
        timeout=float(getattr(settings, "METADOCKER_REQUEST_TIMEOUT", 15.0)),
        max_tick_age_seconds=float(getattr(settings, "METADOCKER_MAX_TICK_AGE_SECONDS", 10.0)),
    )
    try:
        await connection.health()
    except (MetaDockerError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="MetaDocker health check failed; engine was not bound",
        ) from exc
    finally:
        await connection.close()

    # Serialize per-user slot checks on PostgreSQL. The lock is taken only
    # after the bounded external health check, and is held through repository commit.
    locked_user = db.query(User).filter_by(id=user.id).with_for_update().first()
    if not locked_user or not locked_user.is_active or locked_user.is_banned or not locked_user.is_verified:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is unavailable")
    existing = repository.list_for_user(user.id)
    same_active_account = any(
        row.account_reference == payload.account_reference and row.is_active
        for row in existing
    )
    active_count = sum(1 for row in existing if row.is_active)
    limit = _connection_limit(locked_user, db)
    if limit <= 0 or (not same_active_account and active_count >= limit):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your subscription connection limit has been reached",
        )
    try:
        row = repository.upsert_for_user(
            user.id,
            engine_instance_id=payload.engine_instance_id,
            endpoint=payload.endpoint,
            account_reference=payload.account_reference,
            api_key_ciphertext=encrypt_gateway_api_key(payload.api_key) or "",
            engine_version=payload.engine_version,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Engine is already bound or the connection conflicts with an existing record",
        ) from exc
    return _engine_out(row)


@router.delete("/engine/{engine_instance_id}")
async def disable_engine(
    engine_instance_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Disable routing to an engine without deleting its audit record."""
    if not EngineInstanceRepository(db).disable_for_user(user.id, engine_instance_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Engine not found")
    try:
        from web.runtime import get_execution_provider
        provider = get_execution_provider()
        if provider is not None and hasattr(provider, "invalidate_engine"):
            await provider.invalidate_engine(engine_instance_id)
    except Exception as exc:
        logger.warning("Engine cache invalidation failed (%s)", type(exc).__name__)
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
