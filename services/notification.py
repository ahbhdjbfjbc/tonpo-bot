# fx/services/notification.py
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
import asyncio
from html import escape
import logging
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from database.repositories import NotificationRepository, UserRepository
from database.models import Notification, TradeChannelPublication, User
from config.settings import settings

logger = logging.getLogger(__name__)


class NotificationService:
    """
    Handles all user notifications
    """
    
    def __init__(self, db_session: Session, bot=None):
        self.db = db_session
        self.bot = bot  # Telegram bot instance
        self.notification_repo = NotificationRepository(db_session)
        self.user_repo = UserRepository(db_session)
        
        # Notification templates
        self.templates = self._load_templates()
    
    def _load_templates(self) -> Dict[str, str]:
        """Load notification templates"""
        return {
            'trade_executed': (
                "✅ **Trade Executed**\n\n"
                "{order_type} {symbol}\n"
                "📊 Size: {size}\n"
                "💰 Risk: ${risk}\n"
                "🎯 Target: ${reward}\n"
                "📈 R:R: 1:{rr}"
            ),
            'trade_failed': (
                "❌ **Trade Failed**\n\n"
                "الرمز: {symbol}\n"
                "الخطأ: {error}\n\n"
                "تحقق من الاتصال وحاول مجددًا."
            ),
            'connection_success': (
                "✅ **MT5 Connected**\n\n"
                "تم الاتصال بنجاح بالخادم {server}\n"
                "الحساب: {account}\n"
                "الرصيد: ${balance}"
            ),
            'connection_failed': (
                "⚠️ **Connection Issue**\n\n"
                "تعذر الاتصال بـ MT5\n"
                "الخطأ: {error}\n\n"
                "تحقق من بيانات الدخول في /settings"
            ),
            'daily_report': (
                "📊 **Daily Trading Report**\n\n"
                "التاريخ: {date}\n"
                "الصفقات: {trades}\n"
                "الحجم: {volume}\n"
                "الربح/الخسارة: {pnl}\n"
                "نسبة الصفقات الرابحة: {win_rate}%"
            ),
            'subscription_expiring': (
                "⚠️ **Subscription Expiring Soon**\n\n"
                "تنتهي صلاحية خطة {plan} في {expiry}\n"
                "جدد الآن لتجنب انقطاع الخدمة: /upgrade"
            ),
            'subscription_expired': (
                "❌ **Subscription Expired**\n\n"
                "انتهت صلاحية خطة {plan}.\n"
                "تم تحويلك إلى الخطة المجانية.\n"
                "يمكنك الترقية مجددًا من /upgrade"
            ),
            'welcome': (
                "🎉 **Welcome to FX Signal Copier!**\n\n"
                "تم ربط حساب MT5 الخاص بك.\n"
                "ابدأ التداول باستخدام /trade\n"
                "اعرض الإعدادات من /settings"
            ),
            'daily_limit': (
                "⚠️ **Daily Trade Limit Reached**\n\n"
                "استخدمت الحد اليومي البالغ {limit} صفقة.\n"
                "ارفع الحد من /upgrade"
            ),
            'error_alert': (
                "⚠️ **System Alert**\n\n"
                "حدث خطأ:\n"
                "{error}\n\n"
                "تم إبلاغ فريقنا."
            )
        }
    
    async def notify_event(self, user_id: int, event: str, *, title: str, message: str, data: Optional[Dict[str, Any]] = None, event_key: Optional[str] = None, notification_type: str = 'info') -> bool:
        """Persist and optionally deliver one user-owned event idempotently."""
        user = self.user_repo.get_by_telegram_id(user_id)
        if not user:
            return False
        key = event_key or f"{event}:{user.id}:{datetime.utcnow().strftime('%Y-%m-%d')}"
        notification = self.notification_repo.create_notification(
            user.id, title, message, type=notification_type, data=data or {}, event_key=key
        )
        if not notification:
            return False
        if self.bot and not notification.is_delivered:
            delivered = await self.send_telegram(user.telegram_id, message)
            if delivered:
                notification.is_delivered = True
                notification.delivered_at = datetime.utcnow()
                self.db.commit()
            return delivered
        return True

    async def send_telegram(self, user_id: int, message: str, 
                           parse_mode: str = 'Markdown') -> bool:
        """
        Send a Telegram message to a user
        """
        if not self.bot:
            logger.error("Telegram bot not initialized")
            return False
        
        try:
            await self.bot.send_message(
                chat_id=user_id,
                text=message,
                parse_mode=parse_mode
            )
            return True
        except Exception as e:
            logger.error("Failed to send Telegram message to %s (%s)", user_id, type(e).__name__)
            return False
    
    async def notify_trade_executed(self, user_id: int, trade_data: Dict[str, Any]):
        """Notify user about successful trade execution"""
        template = self.templates['trade_executed']
        message = template.format(
            order_type=trade_data['order_type'],
            symbol=trade_data['symbol'],
            size=trade_data['size'],
            risk=trade_data['risk'],
            reward=trade_data['reward'],
            rr=trade_data.get('rr_ratio', 0)
        )
        
        # Send via Telegram
        await self.send_telegram(user_id, message)
        
        # Create in-app notification
        self.notification_repo.create_notification(
            user_id=user_id,
            title="تم تنفيذ الصفقة",
            message=f"{trade_data['order_type']} {trade_data['symbol']} - الحجم: {trade_data['size']}",
            type='success',
            data=trade_data
        )
    
    async def publish_trade_execution(self, signal_receipt_id: int, result: Dict[str, Any]) -> bool:
        """Publish one executed trade to the configured second channel.

        A durable outbox row is marked ``publishing`` before Telegram is called;
        failed rows can be retried while a concurrent duplicate is skipped.
        User identity and account credentials are never included publicly.
        """
        channel_id = getattr(settings, "TRADE_RESULTS_CHANNEL_ID", None)
        if not channel_id or not self.bot:
            return False

        signal = result.get("signal") or {}
        calculated = result.get("calculated") or {}
        row = self.db.query(TradeChannelPublication).filter_by(
            signal_receipt_id=signal_receipt_id
        ).first()
        if row and row.status in {"published", "publishing"}:
            return row.status == "published"
        if row is None:
            row = TradeChannelPublication(
                signal_receipt_id=signal_receipt_id,
                trade_uuid=result.get("trade_id"),
                symbol=str(signal.get("symbol") or "UNKNOWN")[:32],
                order_type=str(signal.get("order_type") or "UNKNOWN")[:32],
                position_size=calculated.get("position_size"),
                entry_price=signal.get("entry"),
                stop_loss=signal.get("stop_loss"),
                take_profits=signal.get("take_profits") or [],
                status="publishing",
            )
            self.db.add(row)
        else:
            row.status = "publishing"
            row.last_error = None
        row.attempts = int(row.attempts or 0) + 1
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            existing = self.db.query(TradeChannelPublication).filter_by(
                signal_receipt_id=signal_receipt_id
            ).first()
            return bool(existing and existing.status == "published")

        tps = ", ".join(str(value) for value in (signal.get("take_profits") or []))
        message = (
            "<b>✅ تنفيذ صفقة</b>\n\n"
            f"<b>{escape(str(signal.get('order_type') or 'UNKNOWN'))} "
            f"{escape(str(signal.get('symbol') or 'UNKNOWN'))}</b>\n"
            f"الحجم: <code>{escape(str(calculated.get('position_size') or '-'))}</code>\n"
            f"الدخول: <code>{escape(str(signal.get('entry') or 'MARKET'))}</code>\n"
            f"وقف الخسارة: <code>{escape(str(signal.get('stop_loss') or '-'))}</code>\n"
            f"الأهداف: <code>{escape(tps or '-')}</code>"
        )
        try:
            sent = await self.bot.send_message(
                chat_id=int(channel_id), text=message, parse_mode="HTML"
            )
            row.status = "published"
            row.telegram_message_id = getattr(sent, "message_id", None)
            row.published_at = datetime.utcnow()
            row.last_error = None
            self.db.commit()
            return True
        except Exception as exc:
            self.db.rollback()
            row = self.db.query(TradeChannelPublication).filter_by(
                signal_receipt_id=signal_receipt_id
            ).first()
            if row:
                row.status = "failed"
                row.last_error = type(exc).__name__[:255]
                self.db.commit()
            logger.error("Trade channel publication failed (%s)", type(exc).__name__)
            return False

    async def notify_trade_failed(self, user_id: int, error: str, trade_data: Dict[str, Any]):
        """Notify user about trade failure"""
        template = self.templates['trade_failed']
        message = template.format(
            symbol=trade_data.get('symbol', 'Unknown'),
            error=error[:100]
        )
        
        await self.send_telegram(user_id, message)
        
        self.notification_repo.create_notification(
            user_id=user_id,
            title="تعذر تنفيذ الصفقة",
            message=f"السبب: {error[:50]}...",
            type='error',
            data={'error': error, 'trade_data': trade_data}
        )
    
    async def notify_connection_status(self, user_id: int, success: bool, 
                                      server: str, account: str, 
                                      balance: Optional[float] = None,
                                      error: Optional[str] = None):
        """Notify user about connection status change"""
        if success:
            template = self.templates['connection_success']
            message = template.format(
                server=server,
                account=account,
                balance=balance or 0
            )
            notif_type = 'success'
            title = "تم الاتصال بـ MT5"
        else:
            template = self.templates['connection_failed']
            message = template.format(error=error or "خطأ غير معروف")
            notif_type = 'error'
            title = "فشل الاتصال"
        
        await self.send_telegram(user_id, message)
        
        self.notification_repo.create_notification(
            user_id=user_id,
            title=title,
            message=message[:100],
            type=notif_type,
            data={'server': server, 'account': account, 'error': error}
        )
    
    async def send_daily_report(self, user_id: int, stats: Dict[str, Any]):
        """Send daily trading report"""
        template = self.templates['daily_report']
        message = template.format(
            date=datetime.utcnow().strftime('%Y-%m-%d'),
            trades=stats.get('trades', 0),
            volume=stats.get('volume', 0),
            pnl=stats.get('pnl', 0),
            win_rate=stats.get('win_rate', 0)
        )
        
        await self.send_telegram(user_id, message)
    
    async def check_subscription_expiry(self):
        """Check for expiring subscriptions and notify users"""
        from services.subscription import SubscriptionService
        
        sub_service = SubscriptionService(self.db)
        expiring_soon = sub_service.get_expiring_soon(days=7)
        
        for user, days_left in expiring_soon:
            template = self.templates['subscription_expiring']
            message = template.format(
                plan=user.subscription_tier,
                expiry=user.subscription_expiry.strftime('%Y-%m-%d')
            )
            
            await self.send_telegram(user.telegram_id, message)
            
            self.notification_repo.create_notification(
                user_id=user.id,
                title="اقتراب انتهاء الاشتراك",
                message=f"تنتهي صلاحية خطة {user.subscription_tier} خلال {days_left} يومًا",
                type='warning',
                data={'expiry': user.subscription_expiry.isoformat()}
            )
    
    async def notify_daily_limit(self, user_id: int, limit: int):
        """Notify user about reaching daily trade limit"""
        template = self.templates['daily_limit']
        message = template.format(limit=limit)
        
        await self.send_telegram(user_id, message)
    
    async def broadcast(self, message: str, user_ids: Optional[List[int]] = None,
                       user_filter: Optional[Dict[str, Any]] = None):
        """
        Broadcast a message to multiple users
        """
        if user_ids:
            users = self.db.query(User).filter(User.telegram_id.in_(user_ids)).all()
        elif user_filter:
            query = self.db.query(User)
            for key, value in user_filter.items():
                if hasattr(User, key):
                    query = query.filter(getattr(User, key) == value)
            users = query.all()
        else:
            users = self.user_repo.get_active_users()
        
        success_count = 0
        fail_count = 0
        
        for user in users:
            try:
                delivered = await self.send_telegram(user.telegram_id, message, parse_mode=None)
                if delivered:
                    success_count += 1
                else:
                    fail_count += 1
                await asyncio.sleep(0.05)  # conservative Telegram rate limiting
            except Exception as e:
                logger.warning("Broadcast delivery failed (%s)", type(e).__name__)
                fail_count += 1
        
        logger.info(f"Broadcast complete: {success_count} success, {fail_count} failed")
        
        return {
            'total': len(users),
            'success': success_count,
            'failed': fail_count
        }
    
    async def send_error_alert(self, error: str, context: Dict[str, Any]):
        """Send error alert to admins"""
        admin_ids = settings.ADMIN_USER_IDS
        
        template = self.templates['error_alert']
        message = template.format(error=error[:200])
        
        for admin_id in admin_ids:
            await self.send_telegram(admin_id, message)
    
    def get_unread_count(self, user_id: int) -> int:
        """Get count of unread notifications for a user"""
        return len(self.notification_repo.get_unread(user_id))
    
    def mark_all_read(self, user_id: int) -> int:
        """Mark all notifications as read for a user"""
        return self.notification_repo.mark_all_as_read(user_id)
