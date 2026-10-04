"""Signals API — list and detail of TradingView / channel signals."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from database.models import SignalReceipt, User
from web.deps import get_current_user, get_db

router = APIRouter(prefix="/api/signals", tags=["signals"])


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
):
    q = db.query(SignalReceipt).filter(SignalReceipt.user_id == user.id)
    if status:
        q = q.filter(SignalReceipt.status == status)
    if source:
        q = q.filter(SignalReceipt.source == source)
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
        "created_at": r.created_at.isoformat() + "Z" if r.created_at else None,
    }
