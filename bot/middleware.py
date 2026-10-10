# fx/bot/middleware.py
import logging
import time
import asyncio  # ← ADD THIS IMPORT!
from datetime import datetime, timezone
from functools import wraps
from typing import Callable, Dict, Any, Optional
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import CallbackContext
from sqlalchemy.orm import Session

from database.repositories import UserRepository
from services.cache import CacheService, RateLimitUnavailable
from services.notification import NotificationService
from services.monitoring import MonitoringService
from config.settings import settings

logger = logging.getLogger(__name__)


class AuthMiddleware:
    """
    Authentication middleware for bot commands
    Checks if user is registered and active
    """
    
    def __init__(self, db_session: Session):
        self.db = db_session
        self.user_repo = UserRepository(db_session)
    
    def wrap(self, handler_func: Callable) -> Callable:
        """
        Wrap a handler function with authentication check
        """
        @wraps(handler_func)
        async def wrapper(update: Update, context: CallbackContext, *args, **kwargs):
            """Added *args, **kwargs to fix the error"""
            user_id = update.effective_user.id
            
            # Check if user exists and is active
            user = self.user_repo.get_by_telegram_id(user_id)
            
            if not user:
                await update.message.reply_text(
                    "❌ You need to register first!\n\n"
                    "Use /register to connect your MT5 account."
                )
                return None  # Return None instead of nothing
            
            if not user.is_active:
                await update.message.reply_text(
                    "❌ Your account is deactivated.\n"
                    "يرجى التواصل مع الدعم للمساعدة."
                )
                return None
            
            if user.is_banned:
                await update.message.reply_text(
                    "❌ Your account has been banned.\n"
                    "يرجى التواصل مع الدعم إذا كنت ترى أن هذا خطأ."
                )
                return None
            
            # Update last active timestamp
            user.last_active = datetime.now(timezone.utc)
            self.db.commit()
            
            # Call the original handler with ALL arguments
            return await handler_func(update, context, *args, **kwargs)  # ← Added await!
        
        return wrapper
    
    def wrap_admin(self, handler_func: Callable) -> Callable:
        """
        Wrap a handler function with admin authentication check
        """
        @wraps(handler_func)
        async def wrapper(update: Update, context: CallbackContext, *args, **kwargs):
            """Added *args, **kwargs to fix the error"""
            user_id = update.effective_user.id
            
            allowed = user_id in set(getattr(settings, 'ADMIN_USER_IDS', []) or [])
            if not allowed:
                if update.effective_message:
                    await update.effective_message.reply_text("❌ وصول غير مصرح به.")
                elif update.callback_query:
                    await update.callback_query.answer("❌ Admin access required", show_alert=True)
                return None
            
            # Call the original handler with ALL arguments
            return await handler_func(update, context, *args, **kwargs)  # ← Added await!
        
        return wrapper


class RateLimitMiddleware:
    """
    Rate limiting middleware to prevent abuse
    Uses Redis for distributed rate limiting
    """
    
    def __init__(self, cache_service: CacheService):
        self.cache = cache_service
        def configured_limit(name: str, fallback: int) -> int:
            try:
                value = int(getattr(settings, name, fallback))
            except (TypeError, ValueError):
                value = fallback
            return value if value > 0 else fallback

        self.default_limits = {
            'trade': (configured_limit('RATE_LIMIT_TRADES', 5), 60),
            'calculate': (configured_limit('RATE_LIMIT_CALCULATIONS', 10), 60),
            'balance': (configured_limit('RATE_LIMIT_BALANCE', 30), 60),
            'positions': (configured_limit('RATE_LIMIT_POSITIONS', 20), 60),
            'settings': (configured_limit('RATE_LIMIT_SETTINGS', 20), 60),
            'default': (configured_limit('RATE_LIMIT_DEFAULT', 30), 60),
        }
    
    def check_rate_limit(self, user_id: int, action: str = 'default') -> tuple:
        """
        Check if user has exceeded rate limit.
        Uses plan-specific
        Uses plan-specific rate_limit_per_second if available.
        Returns (is_allowed, retry_after_seconds)
        """
        limit, period = self.default_limits.get(action, self.default_limits['default'])
        
        # Try to get plan-specific multiplier
        session = None
        try:
            from services.subscription import SubscriptionService
            from database.database import db_manager
            session = db_manager.get_session()
            sub_service = SubscriptionService(session)
            plan = sub_service.get_user_plan(user_id)
            if plan and plan.rate_limit_per_second:
                # Scale limits by plan's rate_limit_per_second relative to default (1).
                multiplier = float(plan.rate_limit_per_second)
                if multiplier > 0:
                    limit = max(1, int(limit * multiplier))
        except Exception:
            pass  # Fall back to default limits.
        finally:
            if session is not None:
                session.close()
        
        # The complete decision/update is one Redis-side atomic operation.
        # Redis failure is deliberately fail-closed for protected handlers.
        key = f"ratelimit:bot:{user_id}:{action}"
        try:
            allowed, retry_after = self.cache.check_rate_limit(key, limit, period)
        except RateLimitUnavailable:
            logger.warning("Rate limiting unavailable; rejecting protected action=%s", action)
            return False, period
        return allowed, (None if allowed else max(0, retry_after))
    
    def wrap(self, action: str = 'default') -> Callable:
        """
        Wrap a handler function with rate limiting
        """
        def decorator(handler_func: Callable) -> Callable:
            @wraps(handler_func)
            async def wrapper(update: Update, context: CallbackContext, *args, **kwargs):
                """Added *args, **kwargs to fix the error"""
                if not update.effective_user:
                    if update.effective_message:
                        await update.effective_message.reply_text("❌ تعذر تحديد المستخدم.")
                    return None
                user_id = update.effective_user.id
                
                # Check rate limit
                allowed, retry_after = self.check_rate_limit(user_id, action)
                
                if not allowed:
                    message = update.effective_message
                    if message:
                        await message.reply_text(
                            f"⏳ *Rate limit exceeded*\n\n"
                            f"يرجى الانتظار {retry_after} ثانية قبل المحاولة مجددًا.",
                            parse_mode=ParseMode.MARKDOWN,
                        )
                    elif update.callback_query:
                        await update.callback_query.answer(
                            f"يرجى الانتظار {retry_after} ثانية.", show_alert=True
                        )
                    return None
                
                # Call the original handler with ALL arguments
                return await handler_func(update, context, *args, **kwargs)  # ← Added await!
            
            return wrapper
        
        return decorator


class ErrorHandler:
    """
    Global error handler for the bot
    Logs errors and notifies admins
    """
    
    def __init__(self, notification_service: NotificationService, 
                 monitoring_service: MonitoringService):
        self.notification = notification_service
        self.monitoring = monitoring_service
    
    async def handle(self, update: Update, context: CallbackContext) -> None:
        """
        Handle errors raised in dispatcher
        """
        # Exception messages and tracebacks may contain submitted credentials.
        logger.error(
            "Exception while handling an update (%s)",
            type(context.error).__name__,
        )

        # Track in monitoring (safe - won't raise)
        try:
            self.monitoring.log_error(
                context.error,
                {
                    'update_id': update.update_id if update else None,
                    'user_id': update.effective_user.id if update and update.effective_user else None,
                    'chat_id': update.effective_chat.id if update and update.effective_chat else None
                }
            )
        except Exception as e:
            logger.warning(
                "Could not log error to monitoring (%s)",
                type(e).__name__,
            )

        # Notify user
        try:
            if update and update.effective_message:
                await update.effective_message.reply_text(
                    "❌ An error occurred while processing your request.\n"
                    "تم إبلاغ فريقنا وسيتابع المشكلة."
                )
        except Exception:
            pass

        # Notify admins for critical errors
        if self._is_critical_error(context.error):
            asyncio.create_task(self._notify_admins(context.error, update))
    
    def _is_critical_error(self, error: Exception) -> bool:
        """Check if error is critical enough to notify admins"""
        critical_types = [
            'ConnectionError',
            'DatabaseError',
            'APIError',
            'AuthenticationError'
        ]
        error_type = error.__class__.__name__
        return error_type in critical_types
    
    async def _notify_admins(self, error: Exception, update: Optional[Update]):
        """Notify admins about critical errors"""
        error_text = (
            f"⚠️ *Critical Error*\n\n"
            f"Type: {error.__class__.__name__}\n"
            "Error details are available in the protected server logs.\n"
        )
        
        if update and update.effective_user:
            error_text += f"User: {update.effective_user.id}\n"
        
        await self.notification.broadcast(
            error_text,
            user_filter={'is_admin': True}
        )


class LoggingMiddleware:
    """
    Logging middleware to track all interactions
    """
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    def wrap(self, handler_func: Callable) -> Callable:
        """
        Wrap handler function with logging
        """
        @wraps(handler_func)
        async def wrapper(update: Update, context: CallbackContext, *args, **kwargs):
            """Added *args, **kwargs to fix the error"""
            start_time = time.time()
            user = update.effective_user
            chat = update.effective_chat
            
            # Log incoming message
            self.logger.info(
                f"Message from {user.id} (@{user.username}) in {chat.type}: "
                f"'{update.message.text if update.message else '[no text]'}'"
            )
            
            try:
                # Call handler with ALL arguments
                result = await handler_func(update, context, *args, **kwargs)  # ← Added await!
                
                # Log success
                duration = time.time() - start_time
                self.logger.info(
                    f"Handler {handler_func.__name__} completed in {duration:.3f}s"
                )
                
                return result
                
            except Exception as e:
                # Log failure
                duration = time.time() - start_time
                self.logger.error(
                    f"Handler {handler_func.__name__} failed after {duration:.3f}s: {e}"
                )
                raise
        
        return wrapper


class PerformanceMiddleware:
    """
    Performance tracking middleware
    """
    
    def __init__(self, monitoring_service: MonitoringService):
        self.monitoring = monitoring_service
        self.tracker = monitoring_service.performance_tracker
    
    def wrap(self, operation_name: str) -> Callable:
        """
        Wrap handler function with performance tracking
        """
        def decorator(handler_func: Callable) -> Callable:
            @wraps(handler_func)
            async def wrapper(update: Update, context: CallbackContext, *args, **kwargs):
                """Added *args, **kwargs to fix the error"""
                user_id = update.effective_user.id if update.effective_user else 'unknown'
                operation_id = f"{operation_name}_{user_id}_{int(time.time())}"
                
                # Start tracking
                self.tracker.start_operation(
                    operation_id,
                    {
                        'user_id': user_id,
                        'operation': operation_name,
                        'chat_type': update.effective_chat.type if update.effective_chat else None
                    }
                )
                
                try:
                    # Call handler with ALL arguments
                    result = await handler_func(update, context, *args, **kwargs)  # ← Added await!
                    
                    # End tracking - success
                    self.tracker.end_operation(operation_id, 'success')
                    
                    return result
                    
                except Exception as e:
                    # End tracking - failure
                    self.tracker.end_operation(operation_id, 'failed')
                    raise
            
            return wrapper
        
        return decorator


class MaintenanceMiddleware:
    """
    Check if bot is in maintenance mode
    """
    
    def __init__(self, cache_service: CacheService):
        self.cache = cache_service
    
    def wrap(self, handler_func: Callable) -> Callable:
        """
        Wrap handler function with maintenance check
        """
        @wraps(handler_func)
        async def wrapper(update: Update, context: CallbackContext, *args, **kwargs):
            """Added *args, **kwargs to fix the error"""
            # Check if maintenance mode is enabled
            maintenance_mode = self.cache.get('system:maintenance_mode', False)
            
            if maintenance_mode:
                # Check if user is admin (admins can bypass)
                user_id = update.effective_user.id
                if user_id not in settings.ADMIN_USER_IDS:
                    await update.message.reply_text(
                        "🔧 *Bot is under maintenance*\n\n"
                        "Please try again later.",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    return None
            
            # Call the original handler with ALL arguments
            return await handler_func(update, context, *args, **kwargs)  # ← Added await!
        
        return wrapper


def combine_middleware(*middleware_wrappers) -> Callable:
    """
    Combine multiple middleware wrappers
    """
    def decorator(handler_func: Callable) -> Callable:
        for wrapper in reversed(middleware_wrappers):
            handler_func = wrapper(handler_func)
        return handler_func
    
    return decorator
