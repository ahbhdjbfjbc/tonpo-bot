"""Authentication endpoints for the web platform."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from config.settings import settings
from database.models import AdminRole, User
from database.repositories import UserRepository
from services.auth import AuthService
from services.subscription import SubscriptionService
from web.deps import get_auth_service, get_current_user, get_db
from web.schemas import LoginRequest, TelegramWebAppLoginRequest, TokenResponse

router = APIRouter(prefix="/api/auth", tags=["auth"])
logger = logging.getLogger(__name__)


def _is_admin(user: User, db: Session | None = None) -> bool:
    if user.telegram_id in set(getattr(settings, "ADMIN_USER_IDS", []) or []):
        return True
    if db is None or not hasattr(db, "query"):
        return False
    return db.query(AdminRole).filter(
        AdminRole.telegram_id == user.telegram_id,
        AdminRole.is_active == True,  # noqa: E712
    ).first() is not None


def _user_public(user: User, db: Session | None = None) -> dict:
    return {
        "id": user.id,
        "telegram_id": user.telegram_id,
        "username": user.telegram_username,
        "first_name": user.first_name,
        "subscription_tier": user.subscription_tier,
        "is_verified": user.is_verified,
        "has_gateway": user.has_gateway_credentials,
        "win_rate": round(user.win_rate, 1) if user.win_rate is not None else 0.0,
        "language": getattr(user, "language", "ar"),
        "is_admin": _is_admin(user, db),
    }


@router.post("/login", response_model=TokenResponse)
def login(
    body: LoginRequest,
    db: Session = Depends(get_db),
    auth: AuthService = Depends(get_auth_service),
):
    """
    Login for web dashboard.
    Accepts either:
      - api_key (from user settings)
      - login_code (one-time code issued by Telegram bot — optional future)
    telegram_id is required to identify the account.
    """
    repo = UserRepository(db)
    user = repo.get_by_telegram_id(body.telegram_id)
    if not user or not user.is_active or user.is_banned:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    authenticated = False
    admin_authenticated = False
    if body.api_key:
        info = auth.validate_api_key(body.api_key)
        if info and info.get("telegram_id") == body.telegram_id:
            authenticated = True

    # Optional admin bootstrap requires a separate explicitly configured key.
    # The JWT signing secret must never be accepted as an API credential.
    admin_api_key = getattr(settings, "ADMIN_API_KEY", None)
    if not authenticated and admin_api_key and body.api_key == admin_api_key:
        admin_ids = set(getattr(settings, "ADMIN_USER_IDS", []) or [])
        if body.telegram_id in admin_ids:
            authenticated = True
            admin_authenticated = True

    if not authenticated:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if body.api_key and not admin_authenticated:
        if not SubscriptionService(db).check_feature_access(body.telegram_id, "api_access"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="API access is not included in your subscription")

    expires = timedelta(hours=settings.JWT_EXPIRY_HOURS)
    token = auth.generate_jwt(user.id, expires_delta=expires)
    return TokenResponse(
        access_token=token,
        expires_in=int(expires.total_seconds()),
        user=_user_public(user, db),
    )


@router.post("/telegram-webapp", response_model=TokenResponse)
def telegram_webapp_login(
    body: TelegramWebAppLoginRequest,
    db: Session = Depends(get_db),
    auth: AuthService = Depends(get_auth_service),
):
    """Authenticate the Mini App using Telegram's signed initData only."""
    verified = auth.verify_telegram_webapp_init_data(
        body.init_data,
        max_age_seconds=int(getattr(settings, "TELEGRAM_WEBAPP_INIT_DATA_MAX_AGE_SECONDS", 86400)),
    )
    if not verified:
        logger.warning("Telegram WebApp auth rejected: stage=init_data_verification")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Telegram session")

    repo = UserRepository(db)
    user = repo.get_by_telegram_id(verified["telegram_id"])
    if not user or not user.is_active or user.is_banned:
        logger.warning("Telegram WebApp auth rejected: stage=account_unavailable")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account unavailable")
    if not user.is_verified:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Complete Telegram registration first")

    expires = timedelta(hours=settings.JWT_EXPIRY_HOURS)
    token = auth.generate_jwt(user.id, expires_delta=expires)
    return TokenResponse(
        access_token=token,
        expires_in=int(expires.total_seconds()),
        user=_user_public(user, db),
    )


@router.get("/me")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _user_public(user, db)
