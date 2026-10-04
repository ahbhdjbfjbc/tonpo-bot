"""Authentication endpoints for the web platform."""
from __future__ import annotations

from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from config.settings import settings
from database.models import User
from database.repositories import UserRepository
from services.auth import AuthService
from web.deps import get_auth_service, get_current_user, get_db
from web.schemas import LoginRequest, TokenResponse

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _user_public(user: User) -> dict:
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
    if body.api_key:
        info = auth.validate_api_key(body.api_key)
        if info and info.get("telegram_id") == body.telegram_id:
            authenticated = True

    # Admin users listed in settings can use a special bootstrap when JWT secret matches
    # and api_key is the JWT_SECRET itself (dev only — still requires telegram_id in ADMIN list)
    if not authenticated and body.api_key and body.api_key == settings.JWT_SECRET:
        admin_ids = set(getattr(settings, "ADMIN_USER_IDS", []) or [])
        if body.telegram_id in admin_ids:
            authenticated = True

    if not authenticated:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    expires = timedelta(hours=settings.JWT_EXPIRY_HOURS)
    token = auth.generate_jwt(user.id, expires_delta=expires)
    return TokenResponse(
        access_token=token,
        expires_in=int(expires.total_seconds()),
        user=_user_public(user),
    )


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return _user_public(user)
