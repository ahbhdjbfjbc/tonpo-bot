"""TradingView Signal Gateway — secure webhook ingress."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from config.settings import settings
from core.models import UnifiedSignal
from services.signal_pipeline import SignalPipeline
from web.deps import get_db
from web.schemas import TradingViewSignalSchema

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

# In-memory rate limit + replay window (bounded; production can move to Redis)
_rate_buckets: Dict[str, list] = defaultdict(list)
_seen_ids: Dict[str, float] = {}
_RATE_LIMIT = 30          # requests per window
_RATE_WINDOW = 60.0       # seconds
_REPLAY_TTL = 600.0       # 10 minutes
_MAX_TIMESTAMP_SKEW = 300  # 5 minutes


def _client_key(request: Request, secret_hint: str) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    ip = (forwarded.split(",")[0].strip() if forwarded else None) or (request.client.host if request.client else "unknown")
    return f"{ip}:{secret_hint[:8] if secret_hint else 'anon'}"


def _check_rate_limit(key: str) -> None:
    now = time.time()
    bucket = _rate_buckets[key]
    _rate_buckets[key] = [t for t in bucket if now - t < _RATE_WINDOW]
    if len(_rate_buckets[key]) >= _RATE_LIMIT:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limit exceeded")
    _rate_buckets[key].append(now)


def _check_replay(external_id: Optional[str], timestamp: Optional[Any]) -> None:
    now = time.time()
    # prune
    stale = [k for k, v in _seen_ids.items() if now - v > _REPLAY_TTL]
    for k in stale:
        _seen_ids.pop(k, None)

    if timestamp is not None:
        try:
            ts = float(timestamp)
            if ts > 1e12:  # ms
                ts = ts / 1000.0
            if abs(now - ts) > _MAX_TIMESTAMP_SKEW:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Timestamp outside allowed window")
        except (TypeError, ValueError):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid timestamp")

    if external_id:
        eid = str(external_id)[:180]
        if eid in _seen_ids:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Duplicate signal (replay protection)")
        _seen_ids[eid] = now


def _authenticate(secret: Optional[str]) -> bool:
    configured = getattr(settings, "TRADINGVIEW_WEBHOOK_SECRET", None)
    if not configured:
        return False
    if not secret:
        return False
    return hmac.compare_digest(str(configured), str(secret))


@router.post("/tradingview")
async def tradingview_webhook(
    request: Request,
    db: Session = Depends(get_db),
    x_tradingview_secret: Optional[str] = Header(None, alias="X-TradingView-Secret"),
    x_webhook_secret: Optional[str] = Header(None, alias="X-Webhook-Secret"),
    authorization: Optional[str] = Header(None),
):
    """
    TradingView → Signal Gateway → SignalPipeline → Risk → Executor → MT5

    Auth: header X-TradingView-Secret (or X-Webhook-Secret / Bearer) must match
    TRADINGVIEW_WEBHOOK_SECRET.

    Never bypasses SignalPipeline / RiskService / TradeExecutor.
    Respects TRADING_DRY_RUN.
    """
    provided = x_tradingview_secret or x_webhook_secret
    if not provided and authorization and authorization.lower().startswith("bearer "):
        provided = authorization[7:].strip()

    if not _authenticate(provided):
        logger.warning("TradingView webhook unauthorized from %s", request.client.host if request.client else "?")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    client_key = _client_key(request, provided or "")
    _check_rate_limit(client_key)

    try:
        raw = await request.body()
        if not raw or len(raw) > 32_768:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid body size")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Malformed JSON")
        if not isinstance(data, dict):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Payload must be a JSON object")
    except HTTPException:
        raise
    except Exception:
        logger.exception("Webhook body read failed")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid payload")

    # Schema validation
    try:
        signal = TradingViewSignalSchema.model_validate(data)
        tps = signal.resolved_tps()
    except Exception as exc:
        logger.info("TradingView schema validation failed: %s", exc)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Schema validation failed: {exc}")

    external_id = signal.id or signal.signal_id or data.get("id") or data.get("signal_id")
    _check_replay(str(external_id) if external_id else None, signal.timestamp)

    # Build canonical payload for existing pipeline adapter
    payload_obj = {
        "action": signal.action,
        "symbol": signal.symbol,
        "stop_loss": signal.stop_loss,
        "take_profits": tps,
        "user_id": signal.user_id,
    }
    if signal.entry is not None:
        payload_obj["entry"] = signal.entry
    if signal.timeframe:
        payload_obj["timeframe"] = signal.timeframe
    if signal.strategy or signal.source:
        payload_obj["strategy"] = signal.strategy or signal.source
    if external_id:
        payload_obj["id"] = str(external_id)

    envelope = UnifiedSignal(
        source="tradingview",
        payload=json.dumps(payload_obj),
        user_id=signal.user_id,
        external_id=str(external_id) if external_id else None,
        received_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )

    # Lazy import executor binding — pipeline needs a trade executor instance.
    # We construct a minimal pipeline with DB; executor is attached by the running app
    # or a no-op dry-run executor when bot is not running.
    from web.runtime import get_signal_pipeline

    try:
        pipeline = get_signal_pipeline(db)
        result = await pipeline.process(envelope)
    except Exception:
        logger.exception("SignalPipeline processing failed")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Processing failed")

    ok_statuses = {"dry_run", "executed", "partial", "confirmation_required", "manual_review", "pending"}
    http_status = 200 if result.get("status") in ok_statuses else 400
    response = {
        "status": result.get("status"),
        "success": bool(result.get("success")),
        "dry_run": bool(getattr(settings, "TRADING_DRY_RUN", True)),
    }
    if result.get("error"):
        response["error"] = result["error"]
    if result.get("receipt_id"):
        response["receipt_id"] = result["receipt_id"]

    logger.info(
        "TradingView signal processed user=%s symbol=%s status=%s dry_run=%s",
        signal.user_id, signal.symbol, response["status"], response["dry_run"],
    )
    return response
