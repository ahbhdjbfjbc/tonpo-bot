"""Admin API — users, system health, audit logs."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from config.settings import settings
from database.models import AdminAuditLog, SignalReceipt, Trade, User
from web.deps import get_db, require_admin

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/health")
def system_health(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    users = db.query(User).count()
    active = db.query(User).filter(User.is_active == True).count()  # noqa: E712
    trades = db.query(Trade).count()
    signals = db.query(SignalReceipt).count()
    return {
        "status": "ok",
        "dry_run": bool(getattr(settings, "TRADING_DRY_RUN", True)),
        "users_total": users,
        "users_active": active,
        "trades_total": trades,
        "signals_total": signals,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


@router.get("/users")
def list_users(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    total = db.query(User).count()
    rows = db.query(User).order_by(User.created_at.desc()).offset(offset).limit(limit).all()
    return {
        "total": total,
        "items": [
            {
                "id": u.id,
                "telegram_id": u.telegram_id,
                "username": u.telegram_username,
                "subscription_tier": u.subscription_tier,
                "is_active": u.is_active,
                "is_banned": u.is_banned,
                "is_verified": u.is_verified,
                "has_gateway": u.has_gateway_credentials,
                "total_trades": getattr(u, "total_trades", None),
                "created_at": u.created_at.isoformat() + "Z" if u.created_at else None,
            }
            for u in rows
        ],
    }


@router.get("/signals")
def admin_signals(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    total = db.query(SignalReceipt).count()
    rows = db.query(SignalReceipt).order_by(SignalReceipt.created_at.desc()).offset(offset).limit(limit).all()
    return {
        "total": total,
        "items": [
            {
                "id": r.id,
                "user_id": r.user_id,
                "source": r.source,
                "status": r.status,
                "signal_text": (r.signal_text or "")[:200],
                "created_at": r.created_at.isoformat() + "Z" if r.created_at else None,
            }
            for r in rows
        ],
    }


@router.get("/trades")
def admin_trades(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    total = db.query(Trade).count()
    rows = db.query(Trade).order_by(Trade.created_at.desc()).offset(offset).limit(limit).all()
    return {
        "total": total,
        "items": [
            {
                "id": t.id,
                "user_id": t.user_id,
                "symbol": t.symbol,
                "order_type": t.order_type,
                "status": t.status,
                "position_size": t.position_size,
                "created_at": t.created_at.isoformat() + "Z" if t.created_at else None,
            }
            for t in rows
        ],
    }


@router.get("/audit")
def audit_logs(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    total = db.query(AdminAuditLog).count()
    rows = (
        db.query(AdminAuditLog)
        .order_by(AdminAuditLog.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {
        "total": total,
        "items": [
            {
                "id": a.id,
                "admin_telegram_id": a.admin_telegram_id,
                "role": a.role,
                "action": a.action,
                "target_type": a.target_type,
                "target_id": a.target_id,
                "result": a.result,
                "failure_reason": a.failure_reason,
                "created_at": a.created_at.isoformat() + "Z" if a.created_at else None,
            }
            for a in rows
        ],
    }
