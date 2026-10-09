"""Authenticated subscription and trial state transitions."""
from __future__ import annotations

from decimal import Decimal
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from database.models import User
from services.subscription import SubscriptionService, TrialService
from services.payment import PaymentService
from config.settings import settings
from web.deps import get_current_user, get_db


class PaymentProofIn(BaseModel):
    payment_id: str = Field(min_length=1, max_length=36)
    tx_hash: str = Field(min_length=1, max_length=100)
    amount: Decimal = Field(gt=0)
    currency: str = Field(min_length=1, max_length=10)
    network: str = Field(min_length=1, max_length=20)
    recipient: str | None = Field(default=None, max_length=100)

router = APIRouter(prefix="/api/subscription", tags=["subscription"])


def _state(user: User, db: Session) -> dict:
    trial = TrialService(db).get_trial_status(user.telegram_id)
    usage = SubscriptionService(db).get_usage_stats(user.telegram_id)
    return {
        "plan": usage.get("plan", user.subscription_tier),
        "status": trial.get("status") if trial.get("status") in {"ACTIVE", "EXPIRED"} else (
            "ACTIVE" if usage.get("expiry") else "FREE"
        ),
        "expiry": usage.get("expiry"),
        "trades_today": usage.get("trades_today", 0),
        "trade_limit": usage.get("trade_limit"),
        "remaining": max(0, (usage.get("trade_limit") or 0) - (usage.get("trades_today") or 0)),
        "features": usage.get("features", {}),
        "trial": trial,
    }


@router.get("/status")
def subscription_status(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _state(user, db)


@router.post("/trial")
def activate_trial(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    eligibility = TrialService(db).check_trial_eligibility(user.telegram_id)
    if not eligibility.get("eligible"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=eligibility.get("reason", "Trial unavailable"))
    result = TrialService(db).start_trial(user.telegram_id)
    if not result.get("success"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=result.get("message", "Trial unavailable"))
    return _state(user, db)


@router.post("/payment/proof")
def submit_payment_proof(
    body: PaymentProofIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Submit untrusted payment proof for manual administrator review."""
    try:
        return PaymentService(db).submit_payment_proof(
            user_id=user.telegram_id, payment_id=body.payment_id,
            tx_hash=body.tx_hash, amount=body.amount, currency=body.currency,
            network=body.network, recipient=body.recipient,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/payment/webhook")
async def payment_webhook():
    """Retained as a non-activating compatibility endpoint.

    Tonpo uses manual administrator payment approval; no webhook can grant
    subscription access.
    """
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
