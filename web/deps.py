"""Shared FastAPI dependencies: DB session, auth, rate limits."""
from __future__ import annotations

from typing import Optional, Generator

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from config.settings import settings
from database.database import db_manager
from database.models import User
from database.repositories import UserRepository
from services.auth import AuthService

security = HTTPBearer(auto_error=False)


def get_db() -> Generator[Session, None, None]:
    if not getattr(db_manager, "_initialized", False):
        db_url = getattr(settings, "DATABASE_URL", None) or None
        db_manager.initialize(db_url)
    session = db_manager.get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_auth_service(db: Session = Depends(get_db)) -> AuthService:
    return AuthService(db)


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
    auth: AuthService = Depends(get_auth_service),
) -> User:
    if not credentials or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    payload = auth.verify_jwt(credentials.credentials)
    if not payload or "user_id" not in payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    user = db.query(User).filter(User.id == payload["user_id"]).first()
    if not user or not user.is_active or user.is_banned:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account unavailable")
    return user


def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
    auth: AuthService = Depends(get_auth_service),
) -> Optional[User]:
    if not credentials or not credentials.credentials:
        return None
    payload = auth.verify_jwt(credentials.credentials)
    if not payload or "user_id" not in payload:
        return None
    user = db.query(User).filter(User.id == payload["user_id"]).first()
    if not user or not user.is_active or user.is_banned:
        return None
    return user


def get_optional_user_strict(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
    auth: AuthService = Depends(get_auth_service),
) -> Optional[User]:
    """Allow anonymous access, but never silently ignore a supplied bad token."""
    if not credentials or not credentials.credentials:
        return None
    payload = auth.verify_jwt(credentials.credentials)
    if not payload or "user_id" not in payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    user = db.query(User).filter(User.id == payload["user_id"]).first()
    if not user or not user.is_active or user.is_banned:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account unavailable")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    """Temporary fail-closed admin gate: only explicitly configured IDs are privileged."""
    admin_ids = set(getattr(settings, "ADMIN_USER_IDS", []) or [])
    if user.telegram_id in admin_ids:
        return user
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
