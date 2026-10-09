"""Persistent, restart-safe daily announcement delivery."""
from __future__ import annotations

from datetime import datetime
import logging
from typing import Any, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database.models import Announcement, AnnouncementDelivery, User

logger = logging.getLogger(__name__)


class AnnouncementService:
    """Manages announcement configuration and at-most-once delivery claims."""

    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def cycle_key(now: Optional[datetime] = None) -> str:
        """One UTC calendar cycle per 24 hours, stable across process restarts."""
        return (now or datetime.utcnow()).strftime("%Y-%m-%d")

    def create(self, *, title: str, message: str, created_by: int, enabled: bool = False, audience: Optional[dict] = None, starts_at=None, ends_at=None) -> Announcement:
        item = Announcement(title=title.strip(), message=message.strip(), created_by=created_by, enabled=enabled, audience=audience, starts_at=starts_at, ends_at=ends_at)
        self.db.add(item)
        self.db.commit()
        self.db.refresh(item)
        return item

    def list(self, limit: int = 100) -> list[Announcement]:
        return self.db.query(Announcement).order_by(Announcement.created_at.desc()).limit(limit).all()

    def eligible_users(self, announcement: Announcement) -> list[User]:
        audience = announcement.audience or {}
        query = self.db.query(User).filter(User.is_active == True, User.is_banned == False)  # noqa: E712
        if audience.get("verified_only"):
            query = query.filter(User.is_verified == True)  # noqa: E712
        tiers = audience.get("subscription_tiers")
        if isinstance(tiers, list) and tiers:
            query = query.filter(User.subscription_tier.in_(tiers))
        return query.order_by(User.id.asc()).all()

    def active_announcements(self, now: Optional[datetime] = None) -> list[Announcement]:
        now = now or datetime.utcnow()
        query = self.db.query(Announcement).filter(Announcement.enabled == True)  # noqa: E712
        rows = query.order_by(Announcement.id.asc()).all()
        return [row for row in rows if (not row.starts_at or row.starts_at <= now) and (not row.ends_at or row.ends_at >= now)]

    def claim(self, announcement_id: int, user_id: int, cycle_key: str) -> bool:
        """Reserve once; a reserved claim is never blindly retried after restart."""
        claim = AnnouncementDelivery(announcement_id=announcement_id, user_id=user_id, cycle_key=cycle_key, status="reserved")
        self.db.add(claim)
        try:
            self.db.commit()
            return True
        except IntegrityError:
            self.db.rollback()
            return False

    def mark(self, announcement_id: int, user_id: int, cycle_key: str, *, delivered: bool, error_code: Optional[str] = None) -> None:
        claim = self.db.query(AnnouncementDelivery).filter_by(announcement_id=announcement_id, user_id=user_id, cycle_key=cycle_key).first()
        if not claim:
            return
        claim.status = "sent" if delivered else "failed"
        claim.error_code = error_code if not delivered else None
        claim.delivered_at = datetime.utcnow() if delivered else None
        self.db.commit()

    async def deliver_cycle(self, bot, now: Optional[datetime] = None) -> dict[str, int]:
        """Send enabled announcements without duplicate delivery per user/cycle."""
        cycle = self.cycle_key(now)
        sent = failed = skipped = 0
        for announcement in self.active_announcements(now):
            for user in self.eligible_users(announcement):
                if not self.claim(announcement.id, user.id, cycle):
                    skipped += 1
                    continue
                try:
                    await bot.send_message(chat_id=user.telegram_id, text=f"{announcement.title}\n\n{announcement.message}")
                    self.mark(announcement.id, user.id, cycle, delivered=True)
                    sent += 1
                except Exception as exc:
                    self.mark(announcement.id, user.id, cycle, delivered=False, error_code=type(exc).__name__)
                    failed += 1
                    logger.warning("Announcement delivery failed (%s)", type(exc).__name__)
        return {"sent": sent, "failed": failed, "skipped": skipped, "cycle": cycle}

    def delivery_status(self, announcement_id: int, cycle_key: Optional[str] = None) -> dict[str, Any]:
        cycle = cycle_key or self.cycle_key()
        rows = self.db.query(AnnouncementDelivery).filter_by(announcement_id=announcement_id, cycle_key=cycle).all()
        return {"cycle": cycle, "total": len(rows), "sent": sum(row.status == "sent" for row in rows), "failed": sum(row.status == "failed" for row in rows), "reserved": sum(row.status == "reserved" for row in rows)}
