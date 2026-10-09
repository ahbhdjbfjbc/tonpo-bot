"""Trades API — open and closed trades."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from database.models import Trade, User
from web.deps import get_current_user, get_db

router = APIRouter(prefix="/api/trades", tags=["trades"])


def _timeline(trade: Trade) -> list[dict]:
    """Expose only lifecycle facts represented by persisted trade state."""
    events = [{"key": "received", "label": "Signal recorded", "state": "complete"}]
    if trade.position_size is not None:
        events.append({"key": "position", "label": "Position calculated", "state": "complete"})
    events.append({
        "key": "execution",
        "label": "Execution result",
        "state": trade.status or "unknown",
        "at": trade.executed_at.isoformat() + "Z" if trade.executed_at else None,
    })
    return events


@router.get("")
@router.get("/")
def list_trades(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status: Optional[str] = Query(None),
):
    q = db.query(Trade).filter(Trade.user_id == user.id)
    if status:
        q = q.filter(Trade.status == status)
    total = q.count()
    rows = q.order_by(Trade.created_at.desc()).offset(offset).limit(limit).all()
    items = []
    for t in rows:
        items.append({
            "id": t.id,
            "symbol": t.symbol,
            "order_type": t.order_type,
            "entry_price": t.entry_price,
            "stop_loss": t.stop_loss,
            "take_profits": t.take_profits,
            "position_size": t.position_size,
            "risk_percentage": t.risk_percentage,
            "risk_amount": t.risk_amount,
            "potential_reward": t.potential_reward,
            "profit_loss": getattr(t, "profit_loss", None),
            "status": t.status,
            "mt_order_ids": t.mt_order_ids,
            "execution_results": t.execution_results,
            "signal_text": t.signal_text,
            "executed_at": t.executed_at.isoformat() + "Z" if t.executed_at else None,
            "created_at": t.created_at.isoformat() + "Z" if t.created_at else None,
        })
    return {"total": total, "items": items, "limit": limit, "offset": offset}


@router.get("/{trade_id}")
def get_trade(
    trade_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    t = db.query(Trade).filter(Trade.id == trade_id, Trade.user_id == user.id).first()
    if not t:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Trade not found")
    return {
        "id": t.id,
        "symbol": t.symbol,
        "order_type": t.order_type,
        "entry_price": t.entry_price,
        "stop_loss": t.stop_loss,
        "take_profits": t.take_profits,
        "position_size": t.position_size,
        "status": t.status,
        "execution_results": t.execution_results,
        "signal_text": t.signal_text,
        "timeline": _timeline(t),
        "executed_at": t.executed_at.isoformat() + "Z" if t.executed_at else None,
        "created_at": t.created_at.isoformat() + "Z" if t.created_at else None,
    }
