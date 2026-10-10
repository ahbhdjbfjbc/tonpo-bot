"""Authenticated WebSocket channel for live dashboard updates.

Does NOT execute trades. Does NOT bypass SignalPipeline / Risk / Executor.
Emits status snapshots derived from the same REST data sources.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from sqlalchemy.orm import Session

from config.settings import settings
from database.database import db_manager
from database.models import SignalReceipt, Trade, User
from services.auth import AuthService

logger = logging.getLogger(__name__)
router = APIRouter(tags=["websocket"])
MAX_WEBSOCKET_MESSAGE_BYTES = 8192

# Active connections: user_id -> set of websockets
_connections: Dict[int, Set[WebSocket]] = {}
_lock = asyncio.Lock()


async def _register(user_id: int, ws: WebSocket) -> None:
    async with _lock:
        _connections.setdefault(user_id, set()).add(ws)


async def _unregister(user_id: int, ws: WebSocket) -> None:
    async with _lock:
        conns = _connections.get(user_id)
        if not conns:
            return
        conns.discard(ws)
        if not conns:
            _connections.pop(user_id, None)


def _auth_user(token: Optional[str], db: Session) -> Optional[User]:
    if not token:
        return None
    auth = AuthService(db)
    payload = auth.verify_jwt(token)
    if not payload or "user_id" not in payload:
        return None
    user = db.query(User).filter(User.id == payload["user_id"]).first()
    if not user or not user.is_active or user.is_banned:
        return None
    return user


def _snapshot(db: Session, user: User) -> Dict[str, Any]:
    """Build a real snapshot — never invent MT5 balances."""
    dry = bool(getattr(settings, "TRADING_DRY_RUN", True))
    recent_signals = (
        db.query(SignalReceipt)
        .filter(SignalReceipt.user_id == user.id)
        .order_by(SignalReceipt.created_at.desc())
        .limit(5)
        .all()
    )
    recent_trades = (
        db.query(Trade)
        .filter(Trade.user_id == user.id)
        .order_by(Trade.created_at.desc())
        .limit(5)
        .all()
    )
    return {
        "type": "snapshot",
        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "dry_run": dry,
        "user_id": user.id,
        "has_gateway": bool(user.has_gateway_credentials),
        "mt5": {
            "connected": False,
            "message": "Not connected" if not user.has_gateway_credentials else "Gateway session required for live metrics",
        },
        "signals": [
            {
                "id": r.id,
                "source": r.source,
                "status": r.status,
                "created_at": r.created_at.isoformat() + "Z" if r.created_at else None,
            }
            for r in recent_signals
        ],
        "trades": [
            {
                "id": t.id,
                "symbol": t.symbol,
                "status": t.status,
                "order_type": t.order_type,
                "created_at": t.created_at.isoformat() + "Z" if t.created_at else None,
            }
            for t in recent_trades
        ],
    }


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    Preferred auth is the first message {"type":"auth","token":"..."}.
    ?token=<JWT> remains temporarily supported for older clients; new clients must
    not put bearer credentials in the URL, where proxies may log them.
    User isolation is enforced: only that user's data is pushed.
    """
    await websocket.accept()
    user: Optional[User] = None
    db: Optional[Session] = None

    try:
        # Legacy compatibility only. New clients authenticate in the first frame.
        token = websocket.query_params.get("token")
        if not getattr(db_manager, "_initialized", False):
            db_manager.initialize(getattr(settings, "DATABASE_URL", None))
        db = db_manager.get_session()

        if token and len(token.encode("utf-8")) <= MAX_WEBSOCKET_MESSAGE_BYTES:
            user = _auth_user(token, db)

        if user is None:
            # Wait briefly for auth message
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=10.0)
                if len(raw.encode("utf-8")) > MAX_WEBSOCKET_MESSAGE_BYTES:
                    await websocket.close(code=status.WS_1009_MESSAGE_TOO_BIG)
                    return
                msg = json.loads(raw)
                if isinstance(msg, dict) and msg.get("type") == "auth":
                    user = _auth_user(msg.get("token"), db)
            except (asyncio.TimeoutError, json.JSONDecodeError, WebSocketDisconnect):
                user = None

        if user is None:
            await websocket.send_json({"type": "error", "detail": "Unauthorized"})
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        await _register(user.id, websocket)
        await websocket.send_json({"type": "connected", "user_id": user.id, "dry_run": bool(getattr(settings, "TRADING_DRY_RUN", True))})
        await websocket.send_json(_snapshot(db, user))

        # Heartbeat / refresh loop + client ping handling
        while True:
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=25.0)
                if len(raw.encode("utf-8")) > MAX_WEBSOCKET_MESSAGE_BYTES:
                    await websocket.close(code=status.WS_1009_MESSAGE_TOO_BIG)
                    break
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if not isinstance(msg, dict):
                    continue
                if msg.get("type") == "ping":
                    await websocket.send_json({
                        "type": "pong",
                        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                    })
                elif msg.get("type") == "refresh":
                    db.expire_all()
                    await websocket.send_json(_snapshot(db, user))
            except asyncio.TimeoutError:
                # periodic snapshot
                try:
                    db.expire_all()
                    await websocket.send_json(_snapshot(db, user))
                except Exception:
                    break
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.error("WebSocket error (%s)", type(exc).__name__)
    finally:
        if user is not None:
            await _unregister(user.id, websocket)
        if db is not None:
            try:
                db.close()
            except Exception:
                pass


async def broadcast_to_user(user_id: int, payload: Dict[str, Any]) -> int:
    """Optional helper for bot/pipeline to push events. Returns send count."""
    async with _lock:
        targets = list(_connections.get(user_id, set()))
    sent = 0
    for ws in targets:
        try:
            await ws.send_json(payload)
            sent += 1
        except Exception:
            await _unregister(user_id, ws)
    return sent
