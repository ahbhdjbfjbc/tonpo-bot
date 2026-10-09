"""Signals API — list and detail of TradingView / channel signals."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from database.models import SignalReceipt, User
from web.deps import get_current_user, get_db

router = APIRouter(prefix="/api/signals", tags=["signals"])


def _signal_timeline(receipt: SignalReceipt) -> list[dict]:
    """Expose only lifecycle facts persisted on the receipt."""
    terminal = receipt.status or "unknown"
    events = [{"key": "received", "label": "Signal received", "state": "complete"}]
    events.append({"key": "decision", "label": "Pipeline decision", "state": terminal})
    if receipt.trade_uuid:
        events.append({"key": "trade", "label": "Trade record", "state": "persisted", "trade_id": receipt.trade_uuid})
    return events


_REASON_COPY = {
    "invalid": ("Invalid signal", "The signal did not pass validation."),
    "duplicate": ("Duplicate signal", "This signal was already processed."),
    "replay": ("Replay detected", "This signal was rejected by replay protection."),
    "subscription_required": ("Subscription inactive", "An active plan is required for this action."),
    "risk_blocked": ("Risk limit exceeded", "The risk controls blocked this signal."),
    "news_blocked": ("News protection active", "Trading is paused for a relevant high-impact event."),
    "news_unavailable": ("News data unavailable", "Trading is blocked until fresh news data is available."),
    "news_stale": ("News data stale", "Trading is blocked until the news snapshot is refreshed."),
    "expired": ("Signal expired", "The signal was outside its allowed execution window."),
    "execution_blocked": ("Execution blocked", "The execution safety controls blocked the order."),
    "unknown": ("Execution state unknown", "The broker outcome is not confirmed. Do not retry automatically; manual reconciliation is required."),
}

def _decision_copy(receipt: SignalReceipt) -> dict | None:
    key = (receipt.rejection_reason or receipt.status or "").lower()
    for code, copy in _REASON_COPY.items():
        if code in key:
            return {"code": code, "title": copy[0], "explanation": copy[1]}
    return None


def _parse_signal_text(text: str) -> dict:
    """Best-effort parse of rendered signal text for display."""
    out = {"symbol": None, "direction": None, "entry": None, "stop_loss": None, "take_profits": []}
    if not text:
        return out
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    if lines:
        parts = lines[0].split()
        if len(parts) >= 2:
            out["direction"] = parts[0]
            out["symbol"] = parts[1]
    for ln in lines[1:]:
        upper = ln.upper()
        if upper.startswith("ENTRY"):
            out["entry"] = ln.split(None, 1)[-1] if " " in ln else None
        elif upper.startswith("SL"):
            out["stop_loss"] = ln.split(None, 1)[-1] if " " in ln else None
        elif upper.startswith("TP"):
            out["take_profits"].append(ln.split(None, 1)[-1] if " " in ln else ln)
    return out


@router.get("")
@router.get("/")
def list_signals(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    symbol: Optional[str] = None,
    direction: Optional[str] = None,
    rejection_reason: Optional[str] = None,
):
    q = db.query(SignalReceipt).filter(SignalReceipt.user_id == user.id)
    if status:
        q = q.filter(SignalReceipt.status == status)
    if source:
        q = q.filter(SignalReceipt.source == source)
    if symbol:
        q = q.filter(SignalReceipt.signal_text.ilike(f"%{symbol.upper()}%"))
    if direction:
        q = q.filter(SignalReceipt.direction == direction.upper())
    if rejection_reason:
        q = q.filter(SignalReceipt.rejection_reason.ilike(f"%{rejection_reason}%"))
    total = q.count()
    rows = q.order_by(SignalReceipt.created_at.desc()).offset(offset).limit(limit).all()
    items = []
    for r in rows:
        parsed = _parse_signal_text(r.signal_text or "")
        items.append({
            "id": r.id,
            "source": r.source,
            "symbol": parsed["symbol"],
            "direction": parsed["direction"],
            "entry": parsed["entry"],
            "stop_loss": parsed["stop_loss"],
            "take_profits": parsed["take_profits"],
            "signal_text": r.signal_text,
            "status": r.status,
            "signal_id": r.signal_id,
            "account_id": r.account_id,
            "validation_status": r.validation_status,
            "risk_status": r.risk_status,
            "risk_reason": r.risk_reason,
            "protection_reason": r.protection_reason,
            "final_decision": r.final_decision,
            "execution_latency_ms": r.execution_latency_ms,
            "rejection_reason": r.rejection_reason,
            "decision": _decision_copy(r),
            "news_status": r.news_status,
            "trade_id": r.trade_uuid,
            "reconciliation_required": r.status == "unknown",
            "timeline": _signal_timeline(r),
            "created_at": r.created_at.isoformat() + "Z" if r.created_at else None,
            "idempotency_key": r.idempotency_key[:16] + "…" if r.idempotency_key else None,
        })
    return {"total": total, "items": items, "limit": limit, "offset": offset}


@router.get("/{signal_id}")
def get_signal(
    signal_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    r = db.query(SignalReceipt).filter(
        SignalReceipt.id == signal_id,
        SignalReceipt.user_id == user.id,
    ).first()
    if not r:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Signal not found")
    parsed = _parse_signal_text(r.signal_text or "")
    return {
        "id": r.id,
        "source": r.source,
        "symbol": parsed["symbol"],
        "direction": parsed["direction"],
        "entry": parsed["entry"],
        "stop_loss": parsed["stop_loss"],
        "take_profits": parsed["take_profits"],
        "signal_text": r.signal_text,
        "status": r.status,
        "rejection_reason": r.rejection_reason,
        "decision": _decision_copy(r),
        "news_status": r.news_status,
        "trade_id": r.trade_uuid,
        "reconciliation_required": r.status == "unknown",
        "timeline": _signal_timeline(r),
        "created_at": r.created_at.isoformat() + "Z" if r.created_at else None,
    }
