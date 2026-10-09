"""Admin API — users, system health, audit logs."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from config.settings import settings
from database.models import AdminAuditLog, AdminSetting, SignalReceipt, Trade, User, SubscriptionPlan, Announcement, PaymentRequest
from web.deps import get_db, require_admin
from services.announcements import AnnouncementService
from services.subscription import SubscriptionService, TrialService
from services.smart_analytics import SmartAnalyticsService
from services.payment import PaymentService

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/health")
def system_health(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    users = db.query(User).count()
    active = db.query(User).filter(User.is_active == True).count()  # noqa: E712
    trades = db.query(Trade).count()
    signals = db.query(SignalReceipt).count()
    kill_switch = db.query(AdminSetting).filter(AdminSetting.key.in_(["kill_switch", "emergency_stop"])).all()
    protection_events = db.query(SignalReceipt).filter(SignalReceipt.status.in_(["risk_blocked", "news_blocked", "news_stale", "news_unavailable", "blocked"])).count()
    return {
        "status": "ok",
        "dry_run": bool(getattr(settings, "TRADING_DRY_RUN", True)),
        "users_total": users,
        "users_active": active,
        "users_trial": db.query(User).filter(User.trial_used == True, User.subscription_tier == "pro").count(),
        "users_subscribed": db.query(User).filter(User.subscription_tier != "free").count(),
        "mt5_connected": db.query(User).filter(User.mt_connected == True).count(),
        "trades_total": trades,
        "signals_total": signals,
        "accepted_signals": db.query(SignalReceipt).filter(SignalReceipt.final_decision.in_(["accepted", "executed"])).count(),
        "rejected_signals": db.query(SignalReceipt).filter(SignalReceipt.final_decision == "rejected").count(),
        "protection_events": protection_events,
        "kill_switch_active": any(str(row.value).lower() == "true" for row in kill_switch),
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


@router.get("/analytics")
def admin_analytics(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Aggregate safe operational metrics; excludes credentials and raw account secrets."""
    rows = db.query(User).filter(User.is_active == True).all()  # noqa: E712
    summaries = [SmartAnalyticsService(db).summary(u.telegram_id, "30d") for u in rows]
    metrics = {}
    for key in ("total_signals", "accepted_signals", "rejected_signals", "executed_trades", "failed_executions", "unknown_executions", "news_protected_signals"):
        metrics[key] = sum((item.get("metrics", {}).get(key) or 0) for item in summaries)
    return {"users": len(rows), "metrics": metrics, "kill_switch_active": any(str(item.value).lower() == "true" for item in db.query(AdminSetting).filter(AdminSetting.key.in_(["kill_switch", "emergency_stop"])).all())}


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
                "rejection_reason": r.rejection_reason,
                "news_status": r.news_status,
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


class AnnouncementIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=160)
    message: str = Field(..., min_length=1, max_length=4000)
    enabled: bool = False
    audience: Optional[dict] = None
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None


class AnnouncementUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=160)
    message: Optional[str] = Field(None, min_length=1, max_length=4000)
    enabled: Optional[bool] = None
    audience: Optional[dict] = None
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None


class PaymentRejectIn(BaseModel):
    reason: str = Field(..., min_length=1, max_length=255)


class SubscriptionExtendIn(BaseModel):
    days: int = Field(..., ge=1, le=366)
    reason: str = Field("admin_extension", min_length=1, max_length=160)


def _announcement_out(item: Announcement) -> dict:
    return {
        "id": item.id, "title": item.title, "message": item.message,
        "enabled": item.enabled, "audience": item.audience or {},
        "starts_at": item.starts_at.isoformat() if item.starts_at else None,
        "ends_at": item.ends_at.isoformat() if item.ends_at else None,
        "created_by": item.created_by,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


@router.get("/plans")
def admin_plans(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    plans = sorted(db.query(SubscriptionPlan).all(), key=lambda plan: plan.display_order)
    return {"items": [{
        "name": plan.name, "tier": plan.tier, "description": plan.description,
        "active": plan.is_active, "visible": plan.is_visible,
        "trial_eligible": plan.trial_eligible, "display_order": plan.display_order,
        "features": plan.features or [], "limits": {
            "max_trades_per_day": plan.max_trades_per_day,
            "max_symbols": plan.max_symbols, "max_connections": plan.max_connections,
        },
    } for plan in plans]}


@router.get("/users/{user_id}")
def admin_user_detail(user_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    trial = TrialService(db).get_trial_status(user.telegram_id)
    latest_signal = db.query(SignalReceipt).filter_by(user_id=user.id).order_by(SignalReceipt.created_at.desc()).first()
    latest_trade = db.query(Trade).filter_by(user_id=user.id).order_by(Trade.created_at.desc()).first()
    return {
        "id": user.id, "telegram_id": user.telegram_id, "username": user.telegram_username,
        "is_active": user.is_active, "is_verified": user.is_verified, "is_banned": user.is_banned,
        "has_gateway": user.has_gateway_credentials, "mt_connected": bool(user.mt_connected),
        "subscription_tier": user.subscription_tier, "subscription_expiry": user.subscription_expiry.isoformat() if user.subscription_expiry else None,
        "trial": trial, "latest_signal_status": latest_signal.status if latest_signal else None,
        "latest_trade_status": latest_trade.status if latest_trade else None,
    }


@router.post("/users/{user_id}/subscription/extend")
def extend_subscription(user_id: int, body: SubscriptionExtendIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    before = user.subscription_expiry.isoformat() if user.subscription_expiry else None
    base = user.subscription_expiry if user.subscription_expiry and user.subscription_expiry > datetime.utcnow() else datetime.utcnow()
    user.subscription_expiry = base + __import__('datetime').timedelta(days=body.days)
    db.add(AdminAuditLog(admin_telegram_id=admin.telegram_id, role="ADMIN", action="subscription_extend", target_type="user", target_id=str(user.id), old_value={"expiry": before}, new_value={"expiry": user.subscription_expiry.isoformat(), "days": body.days}, result="success"))
    db.commit()
    return {"user_id": user.id, "subscription_expiry": user.subscription_expiry.isoformat()}


@router.post("/payment-requests/{payment_id}/approve")
def approve_payment(payment_id: str, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        return PaymentService(db).approve_payment(payment_id=payment_id, admin_id=admin.telegram_id)
    except PermissionError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Payment review authorization required") from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/payment-requests/{payment_id}/reject")
def reject_payment(payment_id: str, body: PaymentRejectIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        return PaymentService(db).reject_payment(payment_id=payment_id, admin_id=admin.telegram_id, reason=body.reason)
    except PermissionError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Payment review authorization required") from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/payment-requests")
def list_payment_requests(
    payment_status: Optional[str] = Query(None, alias="status"),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Authenticated manual-review queue; contains no credentials or secrets."""
    query = db.query(PaymentRequest).order_by(PaymentRequest.created_at.desc())
    if payment_status:
        query = query.filter(PaymentRequest.status == payment_status.strip().lower())
    rows = query.limit(200).all()
    return {"items": [{
        "payment_id": row.uuid, "user_id": row.user_id,
        "plan_tier": row.plan_tier, "billing_period": row.billing_period,
        "amount": str(row.unique_amount), "currency": row.currency,
        "network": row.network, "wallet_address": row.wallet_address,
        "tx_hash": row.tx_hash, "status": row.status,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "proof_submitted_at": row.proof_submitted_at.isoformat() if row.proof_submitted_at else None,
        "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
        "reviewed_by": row.reviewed_by, "rejection_reason": row.rejection_reason,
    } for row in rows]}


@router.get("/announcements")
def list_announcements(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    service = AnnouncementService(db)
    return {"items": [_announcement_out(item) for item in service.list()]}


@router.post("/announcements")
def create_announcement(body: AnnouncementIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    item = AnnouncementService(db).create(title=body.title, message=body.message, created_by=admin.telegram_id, enabled=body.enabled, audience=body.audience, starts_at=body.starts_at, ends_at=body.ends_at)
    db.add(AdminAuditLog(admin_telegram_id=admin.telegram_id, role="ADMIN", action="announcement_create", target_type="announcement", target_id=str(item.id), new_value={"enabled": item.enabled}, result="success"))
    db.commit()
    return _announcement_out(item)


@router.patch("/announcements/{announcement_id}")
def update_announcement(announcement_id: int, body: AnnouncementUpdate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    item = db.query(Announcement).filter(Announcement.id == announcement_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Announcement not found")
    changes = body.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(item, key, value.strip() if isinstance(value, str) else value)
    db.add(AdminAuditLog(admin_telegram_id=admin.telegram_id, role="ADMIN", action="announcement_update", target_type="announcement", target_id=str(item.id), new_value={"fields": list(changes)}, result="success"))
    db.commit()
    return _announcement_out(item)


@router.get("/announcements/{announcement_id}/delivery")
def announcement_delivery(announcement_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return AnnouncementService(db).delivery_status(announcement_id)
