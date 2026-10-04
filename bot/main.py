# fx/bot/main.py
import sys
from pathlib import Path

# Support the documented direct invocation: python bot/main.py.
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import logging
import asyncio
import warnings
import json
from aiohttp import web  # مكتبة الويب اللي ضفناها
from telegram.warnings import PTBUserWarning
from telegram import BotCommand
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    ConversationHandler, MessageHandler, filters
)

from config.settings import settings
from database.database import db_manager
from bot.handlers import CommandHandlers
from database.repositories import UserRepository
from services.subscription import SubscriptionService
from bot.registration import RegistrationHandler
from bot.trading import TradingHandler
from bot.settings import SettingsHandler
from bot.admin import AdminHandler
from bot.middleware import AuthMiddleware, RateLimitMiddleware, ErrorHandler
#from services.mt5_manager import MT5ConnectionManager
from services.notification import NotificationService
from services.cache import CacheService
from services.queue import QueueService, AsyncTaskManager
from services.monitoring import MonitoringService
from database.db_persistence import DBPersistence
from gateway_client import ExecutionProvider
from core.models import UnifiedSignal
from core.exceptions import SignalParseError
from services.signal_pipeline import SignalPipeline
try:
    from web.runtime import set_runtime
except ImportError:
    set_runtime = None

logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

class Bot:
    """
    Main bot class - initializes and runs the Telegram bot
    """

    def __init__(self):
        # Initialize database
        db_manager.initialize(settings.DATABASE_URL)
        self.db = db_manager.get_session()
        
        # Initialize sync services
        self.cache = CacheService()
        self.queue = QueueService()
        self.task_manager = AsyncTaskManager()
        self.notification = NotificationService(self.db, None)
        self.monitoring = MonitoringService(self.db)
        self.mt5_manager = None 
        # Initialize all handler objects synchronously — no async needed yet
        self.command_handlers = CommandHandlers(self.db, None)   # bot set after build
        self.user_repo = UserRepository(self.db)
        self.sub_service = SubscriptionService(self.db)
        self.registration     = RegistrationHandler(self.db, None, mt5_manager=None)
        self.trading          = TradingHandler(self.db, None, mt5_manager=None)
        self.settings_handler = SettingsHandler(self.db, None)
        self.admin            = AdminHandler(self.db, None)
        self.auth_middleware  = AuthMiddleware(self.db)
        self.rate_limiter     = RateLimitMiddleware(self.cache)

        # Build application — handlers registered BEFORE build() via pre_init isn't
        # available, so we build first then add_handler before initialize() is called
        persistence = DBPersistence()
        self.application = (
            ApplicationBuilder()
            .token(settings.BOT_TOKEN)
            .persistence(persistence)
            .post_init(self._post_init)
            .post_shutdown(self._post_shutdown)
            .build()
        )

        # bot reference is available after build()
        self.bot = self.application.bot
        self.notification.bot        = self.bot
        self.command_handlers.bot    = self.bot
        self.registration.bot        = self.bot
        self.trading.bot             = self.bot
        self.trading.trade_executor.bot = self.bot
        self.trading.trade_executor.notification.bot = self.bot
        self.settings_handler.bot    = self.bot
        self.admin.bot               = self.bot

        # Error handler needs notification + monitoring (both sync-ready)
        self.error_handler = ErrorHandler(self.notification, self.monitoring)

        # Suppress expected per_message warning
        warnings.filterwarnings('ignore', message=".*per_message=False.*", category=PTBUserWarning)

        # Register all handlers NOW
        self._setup_middleware()
        self._setup_handlers()
        
        # Initialize execution provider
        self.execution_provider = ExecutionProvider(use_gateway=settings.USE_GATEWAY)

    def _setup_middleware(self):
        self.application.add_error_handler(self.error_handler.handle)

    def _setup_handlers(self):
        app = self.application

        # Basic commands (no auth)
        app.add_handler(CommandHandler("start", self.command_handlers.start))
        app.add_handler(CommandHandler("help",  self.command_handlers.help))
        app.add_handler(CommandHandler("about", self.command_handlers.about))
        app.add_handler(CommandHandler("referral", self.command_handlers.referral))
        app.add_handler(CommandHandler("support", self.admin.open_support_ticket))

        # Registration conversation
        reg_conv = ConversationHandler(
            entry_points=[CommandHandler("register", self.registration.start)],
            states=self.registration.get_states(),
            fallbacks=[
                CommandHandler("cancel", self.registration.cancel),
                CommandHandler("register", self.registration.start),
            ],
            name="registration",
            persistent=True,
            per_message=False,
            allow_reentry=True,
        )
        app.add_handler(reg_conv)

        # Trading conversation
        trade_conv = ConversationHandler(
            entry_points=[CommandHandler("trade", self.auth_middleware.wrap(self.trading.start_trade))],
            states=self.trading.get_states(),
            fallbacks=[
                CommandHandler("cancel", self.trading.cancel),
                CommandHandler("trade", self.auth_middleware.wrap(self.trading.start_trade)),
            ],
            name="trading",
            persistent=True,
            per_message=False,
            allow_reentry=True,
        )
        app.add_handler(trade_conv)

        # Calculate conversation
        calc_conv = ConversationHandler(
            entry_points=[CommandHandler("calculate", self.auth_middleware.wrap(self.trading.start_calculate))],
            states=self.trading.get_states(),
            fallbacks=[
                CommandHandler("cancel", self.trading.cancel),
                CommandHandler("calculate", self.auth_middleware.wrap(self.trading.start_calculate)),
            ],
            name="calculate",
            persistent=True,
            per_message=False,
            allow_reentry=True,
        )
        app.add_handler(calc_conv)

        # Settings conversation
        settings_conv = ConversationHandler(
            entry_points=[CommandHandler("settings", self.auth_middleware.wrap(self.settings_handler.start))],
            states=self.settings_handler.get_states(),
            fallbacks=[
                CommandHandler("cancel", self.settings_handler.cancel),
                CommandHandler("settings", self.auth_middleware.wrap(self.settings_handler.start)),
            ],
            name="settings",
            persistent=True,
            per_message=False,
            allow_reentry=True,
        )
        app.add_handler(settings_conv)

        # Admin commands
        admin_conv = ConversationHandler(
            entry_points=[
                CommandHandler("admin", self.auth_middleware.wrap_admin(self.admin.dashboard))
            ],
            states=self.admin.get_states(),
            fallbacks=[
                CommandHandler("cancel", self.admin.cancel),
                CommandHandler("admin", self.auth_middleware.wrap_admin(self.admin.dashboard)),
            ],
            name="admin",
            persistent=True,
            per_message=False,
            allow_reentry=True,
        )
        app.add_handler(admin_conv)
        
        # Quick admin commands
        app.add_handler(CommandHandler("stats",     self.auth_middleware.wrap_admin(self.admin.stats)))
        app.add_handler(CommandHandler("broadcast", self.auth_middleware.wrap_admin(self.admin.broadcast)))

        # Authenticated commands
        for cmd, handler in [
            ("balance",   self.command_handlers.balance),
            ("positions", self.command_handlers.positions),
            ("history",   self.command_handlers.history),
            ("profile",   self.command_handlers.profile),
            ("upgrade",   self.command_handlers.upgrade),
        ]:
            callback = self.auth_middleware.wrap(handler) if cmd in {"balance", "positions", "history"} else handler
            app.add_handler(CommandHandler(cmd, callback))

        # Callback query router
        app.add_handler(CallbackQueryHandler(self._handle_callback))
        app.add_handler(MessageHandler(filters.UpdateType.CHANNEL_POST & filters.TEXT,
                                       self.telegram_channel_signal))

    # ==============================================================
    # بداية الأكواد الجديدة الخاصة بـ TradingView Webhook
    # ==============================================================
    async def tv_webhook_handler(self, request):
        """Authenticate and route TradingView alerts through the common pipeline."""
        try:
            provided = request.headers.get('X-TradingView-Secret', '')
            if not SignalPipeline.authenticate_tradingview(provided):
                return web.json_response({'error': 'unauthorized'}, status=401)
            data = await request.json()
            user_id = int(data.get('user_id'))
            envelope = UnifiedSignal(source='tradingview', payload=json.dumps(data), user_id=user_id,
                                     external_id=str(data.get('id') or '') or None)
            result = await SignalPipeline(self.db, self.trading.trade_executor).process(envelope)
            status = 200 if result.get('status') in {'dry_run', 'executed', 'partial', 'confirmation_required', 'manual_review'} else 400
            return web.json_response({'status': result.get('status')}, status=status)
        except (json.JSONDecodeError, TypeError, ValueError, SignalParseError):
            return web.json_response({'error': 'invalid payload'}, status=400)
        except Exception:
            logger.error('TradingView signal processing failed', exc_info=True)
            return web.json_response({'error': 'internal error'}, status=500)

    async def telegram_channel_signal(self, update, context):
        """Accept channel signals only from explicitly allowlisted Telegram chats."""
        message = update.channel_post
        if not message or not SignalPipeline.authenticate_telegram_channel(message.chat_id):
            return
        payload = message.text or message.caption or ''
        if not payload:
            return
        from database.models import User
        users = self.db.query(User).filter_by(is_active=True, is_verified=True, is_banned=False).all()
        for user in users:
            try:
                envelope = UnifiedSignal(source='telegram_channel', payload=payload,
                                         user_id=user.telegram_id,
                                         external_id=f'{message.chat_id}:{message.message_id}')
                result = await SignalPipeline(self.db, self.trading.trade_executor).process(envelope)
                if result.get('status') not in {'duplicate', 'dry_run'}:
                    await self.notification.send_telegram(user.telegram_id,
                                                          f"إشارة قناة جديدة: {result.get('status', 'unknown')}")
            except Exception:
                logger.exception('Telegram channel signal routing failed')

    async def start_tv_server(self):
        """دالة لتشغيل سيرفر الويب الخاص باستقبال الإشارات"""
        app = web.Application()
        app.router.add_post('/webhook', self.tv_webhook_handler)
        runner = web.AppRunner(app)
        await runner.setup()
        
        # تشغيل السيرفر على بورت 8080 (أو حسب المنصة مثل Render/Railway)
        site = web.TCPSite(runner, settings.TRADINGVIEW_WEBHOOK_HOST,
                            settings.TRADINGVIEW_WEBHOOK_PORT)
        await site.start()
        logger.info("TradingView webhook listening on configured port %s", settings.TRADINGVIEW_WEBHOOK_PORT)
    # ==============================================================
    # نهاية الأكواد الجديدة
    # ==============================================================

    async def _post_init(self, application):
        """Called by PTB after event loop starts — safe for async init only"""
        logger.info("Initializing async services...")
        
        # The authenticated ingress may stay available in dry-run; execution remains blocked.
        if settings.ENABLE_WEBHOOKS and settings.TRADINGVIEW_WEBHOOK_SECRET:
            asyncio.create_task(self.start_tv_server())
        
        # Avoid even opening a gateway connection during a dry run.
        if not settings.TRADING_DRY_RUN:
            try:
                await self.execution_provider.initialize(settings.gateway_config)
                self._load_gateway_credentials()
                logger.info("Gateway initialized successfully")
            except Exception as e:
                logger.error(f"Gateway initialization failed: {e}")
        else:
            logger.info("Dry-run enabled: gateway trade execution is disabled")

        # Inject into handlers regardless of gateway success/failure
        self.registration.execution_provider = self.execution_provider
        self.trading.execution_provider = self.execution_provider
        self.trading.mt5_manager_ready.set()
        self.settings_handler.execution_provider = self.execution_provider

        # Share pipeline/executor/gateway with the web platform when available
        if set_runtime is not None:
            try:
                set_runtime(
                    executor=self.trading.trade_executor,
                    execution_provider=self.execution_provider,
                )
            except Exception:
                pass
        
        from telegram import BotCommandScopeChat
        # Default commands (all users)
        user_commands = [
            BotCommand("start",     "بدء البوت"),
            BotCommand("help",      "عرض المساعدة"),
            BotCommand("about",     "معلومات عن البوت"),
            BotCommand("register",  "تسجيل حساب MT5"),
            BotCommand("trade",     "إنشاء صفقة"),
            BotCommand("calculate", "حساب المخاطر دون تداول"),
            BotCommand("balance",   "عرض رصيد الحساب"),
            BotCommand("positions", "عرض الصفقات المفتوحة"),
            BotCommand("history",   "عرض سجل الصفقات"),
            BotCommand("settings",  "ضبط الإعدادات"),
            BotCommand("profile",   "عرض ملفك الشخصي"),
            BotCommand("upgrade",   "ترقية الاشتراك"),
            BotCommand("referral",  "رابط الإحالة"),
            BotCommand("support",   "فتح تذكرة دعم"),
        ]
        await self.bot.set_my_commands(user_commands)
        
        # Admin commands (only visible to admins)
        admin_commands = user_commands + [
            BotCommand("admin",     "👑 لوحة المشرف"),
            BotCommand("stats",     "👑 إحصاءات النظام"),
            BotCommand("broadcast", "👑 رسالة جماعية"),
        ]
        
        for admin_id in settings.ADMIN_USER_IDS:
            try:
                await self.bot.set_my_commands(
                    admin_commands,
                    scope=BotCommandScopeChat(chat_id=admin_id)
                )
            except Exception as e:
                logger.warning(f"Could not set admin commands for {admin_id}: {e}")

        # Keep the first Telegram smoke test limited to incoming commands.
        if not settings.TRADING_DRY_RUN:
            application.job_queue.run_once(
                lambda ctx: asyncio.ensure_future(self._background_tasks()),
                when=0,
                name="background_tasks"
            )
        else:
            logger.info("Dry-run enabled: automatic background tasks are disabled")

        logger.info("Bot initialized successfully")

    async def _post_shutdown(self, application):
        """Shut down all services — fast and clean"""
        logger.info("Shutting down...")

        # 1. Cancel all background tasks immediately
        tasks = [t for t in asyncio.all_tasks()
                 if t is not asyncio.current_task() and not t.done()]

        for task in tasks:
            task.cancel()

        if tasks:
            # Give tasks 2 seconds to finish, then move on
            done, pending = await asyncio.wait(tasks, timeout=2.0)
            if pending:
                logger.warning(f"{len(pending)} tasks didn't stop in time — forcing")

        # 2. Stop gateway connections
        if getattr(self, 'execution_provider', None):
            try:
                await asyncio.wait_for(self.execution_provider.shutdown(), timeout=5.0)
            except Exception:
                pass

        # 3. Close Redis/cache
        if hasattr(self, 'cache') and self.cache:
            try:
                self.cache.close()
            except Exception:
                pass

        # 4. Close database
        if self.db:
            try:
                self.db.close()
            except Exception:
                pass

        try:
            db_manager.close()
        except Exception:
            pass

        logger.info("Bot stopped successfully")

    async def _handle_callback(self, update, context):
        query = update.callback_query
        user_id = update.effective_user.id
        data = query.data
        
        logger.debug(f"Callback received: {data} from user {user_id}")

        if data.startswith('signal_confirm:') or data.startswith('signal_cancel:'):
            try:
                receipt_id = int(data.split(':', 1)[1])
                pipeline = SignalPipeline(self.db, self.trading.trade_executor)
                result = (await pipeline.confirm(user_id, receipt_id)
                          if data.startswith('signal_confirm:')
                          else await pipeline.cancel(user_id, receipt_id))
                await query.answer()
                await query.edit_message_text(f"حالة الإشارة: {result.get('status', 'unknown')}")
            except (TypeError, ValueError):
                await query.answer('إجراء غير صالح', show_alert=True)
            return

        if data == 'noop':
            await query.answer()
            return
        
        if data.startswith('admin:') or data.startswith('admin_') or data.startswith('user_'):
            # Verify admin status
            if not self.admin.has_permission(user_id, 'users.view'):
                await query.answer("❌ Admin access required", show_alert=True)
                logger.warning("Non-admin attempted admin callback")
                return
                
            # Call the admin handler's callback method
            try:
                await self.admin.handle_callback(update, context)
            except Exception as exc:
                # Avoid logging callback payloads or exception text that may
                # contain user supplied content or sensitive database values.
                logger.error("Admin callback failed (%s)", type(exc).__name__)
                try:
                    await query.answer("تعذر تنفيذ الإجراء. حاول مجددًا.", show_alert=True)
                except Exception:
                    pass
        
        elif data.startswith('trade_') or data.startswith('trade:'):
            # Verify user is registered and active
            user = self.user_repo.get_by_telegram_id(user_id)
            if not user:
                await query.answer("❌ Please register first using /register", show_alert=True)
                return
            if not user.is_active:
                await query.answer("❌ Your account is deactivated", show_alert=True)
                return
            if user.is_banned:
                await query.answer("❌ Your account has been banned", show_alert=True)
                return
                
            # Forward to trading handler's confirm_trade method
            await self.trading.confirm_trade(update, context)

        elif data.startswith('risk_'):
            user = self.user_repo.get_by_telegram_id(user_id)
            if not user or not user.is_verified or not user.is_active or user.is_banned:
                await query.answer("يرجى إكمال التسجيل أولًا باستخدام /register", show_alert=True)
                return
            action = data.removeprefix('risk_')
            if action in {'0.5', '1.0', '2.0'}:
                user.default_risk_factor = float(action) / 100
                self.db.commit()
                await query.answer()
                await query.edit_message_text(f"✅ تم ضبط المخاطرة الافتراضية على {action}%.")
            elif action == 'custom':
                await query.answer()
                await query.edit_message_text(
                    "لإدخال نسبة مخصصة، افتح /settings ثم إعدادات المخاطر."
                )
            else:
                await query.answer("إعداد المخاطر غير معروف", show_alert=True)
        
        elif data.startswith('settings_') or data.startswith('settings:'):
            # Verify user is registered and active
            user = self.user_repo.get_by_telegram_id(user_id)
            if not user:
                await query.answer("❌ Please register first using /register", show_alert=True)
                return
            if not user.is_active:
                await query.answer("❌ Your account is deactivated", show_alert=True)
                return
            if user.is_banned:
                await query.answer("❌ Your account has been banned", show_alert=True)
                return
            
            # Forward to settings handler's handle_menu method
            await self.settings_handler.handle_menu(update, context)
        
        elif data.startswith('confirm_'):
            # Registration doesn't require auth check
            await self.registration.confirm_credentials(update, context)
        
        elif data.startswith('plan_'):
            # Can be accessed by anyone, but check registration for upgrades
            if data == 'plan_compare':
                from bot.callbacks import CallbackHandlers
                callbacks = CallbackHandlers(self.db, self.bot, self.execution_provider)
                await query.answer()
                await callbacks.handle_plan(update, context, ['list'])
            elif data in ['plan_free', 'plan_basic', 'plan_pro', 'plan_enterprise']:
                user = self.user_repo.get_by_telegram_id(user_id)
                if not user:
                    await query.answer("❌ Please register first", show_alert=True)
                    return
                
                from bot.callbacks import CallbackHandlers
                callbacks = CallbackHandlers(self.db, self.bot, self.execution_provider)
                tier = data.replace('plan_', '')
                await callbacks.handle_plan(update, context, ['select', tier])
            else:
                await query.answer("Unknown plan action")
        
        elif data.startswith('pay_') or data.startswith('period_'):
            user = self.user_repo.get_by_telegram_id(user_id)
            if not user:
                await query.answer("❌ Please register first", show_alert=True)
                return
            await self._handle_payment_callback(update, context, data, user)
        
        # Handle notification interactions
        elif data.startswith('notification_') or data.startswith('notify_'):
            user = self.user_repo.get_by_telegram_id(user_id)
            if not user:
                await query.answer("❌ Please register first", show_alert=True)
                return
            
            from bot.callbacks import CallbackHandlers
            callbacks = CallbackHandlers(self.db, self.bot, self.execution_provider)
            
            # Parse action
            if data.startswith('notification_'):
                action = data.replace('notification_', '')
            else:
                action = data.replace('notify_', '')
                
            await callbacks.handle_notification(update, context, [action])
        
        elif data.startswith('position_'):
            user = self.user_repo.get_by_telegram_id(user_id)
            if not user:
                await query.answer("❌ Please register first", show_alert=True)
                return
            
            from bot.callbacks import CallbackHandlers
            callbacks = CallbackHandlers(self.db, self.bot, self.execution_provider)
            
            # Parse action and position ID
            parts = data.split('_')
            if len(parts) >= 3:
                action = parts[1]
                position_id = '_'.join(parts[2:])
                await callbacks.handle_position(update, context, [action, position_id])
            else:
                await query.answer("Invalid position data")
        
        # Handle pagination
        elif '_page_' in data:
            parts = data.split('_page_')
            if len(parts) == 2:
                prefix = parts[0]
                page = parts[1]
                
                from bot.callbacks import CallbackHandlers
                callbacks = CallbackHandlers(self.db, self.bot, self.execution_provider)
                await callbacks.handle_pagination(update, context, [prefix, page])
            else:
                await query.answer("Invalid pagination data")
        
        # Handle help section navigation
        elif data.startswith('help_'):
            from bot.callbacks import CallbackHandlers
            callbacks = CallbackHandlers(self.db, self.bot, self.execution_provider)
            
            section = data.replace('help_', '')
            await callbacks.handle_help(update, context, [section])
        
        elif data.startswith('conn_') or data.startswith('api_'):
            user = self.user_repo.get_by_telegram_id(user_id)
            if not user:
                await query.answer("❌ Please register first", show_alert=True)
                return
            if not user.is_active:
                await query.answer("❌ Your account is deactivated", show_alert=True)
                return
            if user.is_banned:
                await query.answer("❌ Your account has been banned", show_alert=True)
                return
            context.user_data.setdefault('settings_user_id', user_id)
            if data.startswith('conn_'):
                await self.settings_handler.handle_connection(update, context)
            else:
                await self.settings_handler.handle_api(update, context)
        
        else:
            logger.warning(f"Unknown callback data received: {data} from user {user_id}")
            await query.answer("Unknown action", show_alert=False)
        
    async def _handle_payment_callback(self, update, context, data, user):
        query = update.callback_query
        user_id = update.effective_user.id
        
        from services.payment import PaymentService
        from bot.keyboards import get_payment_pending_keyboard, get_upgrade_keyboard
        payment_service = PaymentService(self.db)
        
        if data.startswith('period_monthly_') or data.startswith('period_yearly_'):
            parts = data.split('_', 2)
            period = parts[1]
            plan_tier = parts[2]
            
            context.user_data['upgrade_period'] = period
            context.user_data['upgrade_plan'] = plan_tier
            
            plan = self.sub_service.get_plan(plan_tier)
            price = plan.price_yearly if period == 'yearly' else plan.price_monthly
            
            await query.edit_message_text(
                f"*{plan_tier.title()} Plan — {period.title()}*\n\n"
                f"💰 Price: ${price}\n\n"
                f"Choose payment method:",
                parse_mode='Markdown',
                reply_markup=get_upgrade_keyboard(plan_tier)
            )
            return
        
        if data.startswith('pay_usdt_') or data.startswith('pay_btc_'):
            parts = data.split('_', 2)
            currency = parts[1].upper()
            plan_tier = parts[2]
            period = context.user_data.get('upgrade_period', 'monthly')
            
            try:
                result = payment_service.create_payment_request(
                    user_id=user_id,
                    plan_tier=plan_tier,
                    billing_period=period,
                    currency=currency
                )
                
                network_name = 'Ethereum (ERC-20)' if currency == 'USDT' else 'Bitcoin'
                
                await query.edit_message_text(
                    f"💳 *Payment Request Created*\n\n"
                    f"*Plan:* {plan_tier.title()} ({period})\n"
                    f"*Amount:* `{result['amount']}` {currency}\n"
                    f"*Network:* {network_name}\n\n"
                    f"*Send exactly this amount to:*\n"
                    f"`{result['wallet_address']}`\n\n"
                    f"⚠️ *Send EXACTLY `{result['amount']}` {currency}*\n"
                    f"The unique amount identifies your payment.\n\n"
                    f"⏰ Expires in {result['expires_in_minutes']} minutes\n\n"
                    f"Your plan will activate automatically once "
                    f"the transaction is confirmed on-chain.",
                    parse_mode='Markdown',
                    reply_markup=get_payment_pending_keyboard(result['payment_id'])
                )
                
            except Exception as e:
                await query.edit_message_text(f"❌ تعذر إنشاء عملية الدفع: {e}")
            return
        
        if data.startswith('pay_check_'):
            payment_id = data.replace('pay_check_', '')
            pending = payment_service.get_pending_payment(user_id)
            
            if not pending:
                await query.edit_message_text(
                    "✅ No pending payment found.\n\n"
                    "Your plan may have already been activated, "
                    "or the payment expired.\n\n"
                    "Use /upgrade to try again."
                )
            else:
                await query.answer(
                    f"⏳ Still waiting... {pending['minutes_left']} min left",
                    show_alert=True
                )
            return
        
        if data.startswith('pay_cancel_'):
            payment_service._cancel_pending(user.id)
            await query.edit_message_text(
                "❌ Payment cancelled.\n\nUse /upgrade to try again."
            )
            return
            
    async def _background_tasks(self):
        """Run background tasks with proper cancellation handling"""
        async def run_every(coro_fn, seconds):
            try:
                while True:
                    try:
                        await asyncio.sleep(seconds)
                        await coro_fn()
                    except asyncio.CancelledError:
                        logger.info(f"Background task {coro_fn.__name__} cancelled")
                        break
                    except Exception as e:
                        logger.error(f"Background task error in {coro_fn.__name__}: {e}")
                        await asyncio.sleep(5)
            except asyncio.CancelledError:
                logger.info(f"run_every task cancelled")
                raise

        async def process_expired():
            try:
                from services.subscription import SubscriptionService
                sub_service = SubscriptionService(self.db)
                count = sub_service.process_expired(notification_service=self.notification)
                if count > 0:
                    logger.info(f"Processed {count} expired subscriptions")
            except Exception as e:
                logger.error(f"Error processing expired subscriptions: {e}")

        async def collect_metrics():
            try:
                self.monitoring.collect_metrics()
            except Exception as e:
                logger.error(f"Error collecting metrics: {e}")
        
        async def check_expiry_warnings():
            try:
                await self.notification.check_subscription_expiry()
            except Exception as e:
                logger.error(f"Error checking subscription expiry: {e}")
        
        tasks = [
            asyncio.create_task(run_every(self._check_connections, 300), name="check_connections"),
            asyncio.create_task(run_every(collect_metrics, 900), name="collect_metrics"),
            asyncio.create_task(run_every(process_expired, 86400), name="process_expired"),
            asyncio.create_task(run_every(check_expiry_warnings, 43200), name="check_expiry_warnings"),
        ]
        
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            logger.info("Background tasks cancelled, cleaning up...")
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

    async def _check_connections(self):
        from database.repositories import UserRepository
        repo = UserRepository(self.db)
        users = repo.get_users_needing_connection_check(minutes=30)
        for user in users:
            try:
                if not self.execution_provider:
                    return
                await self.execution_provider.get_connection(user.telegram_id)
            except Exception as e:
                logger.warning(f"Connection check failed for user {user.telegram_id}: {e}")
                await self.notification.send_telegram(
                    user.telegram_id,
                    "⚠️ *Connection Alert*\n\nUnable to connect to your MT5 account. "
                    "Please check your credentials in /settings",
                    parse_mode='Markdown'
                )

    def _load_gateway_credentials(self):
        """Load stored gateway credentials from database into GatewayManager"""
        if not self.execution_provider or not self.execution_provider.gateway_manager:
            return
            
        from database.repositories import UserRepository
        user_repo = UserRepository(self.db)
        gateway_users = user_repo.get_gateway_users()
        
        loaded = 0
        for user in gateway_users:
            try:
                self.execution_provider.gateway_manager.load_user_credentials(
                    telegram_id=user.telegram_id,
                    api_key=user.gateway_api_key,
                    gateway_account_id=user.gateway_account_id,
                )
                loaded += 1
            except Exception as e:
                logger.warning(f"Failed to load gateway credentials for user {user.telegram_id}: {e}")
                
        logger.info(f"Loaded gateway credentials for {loaded} users")


    def run(self):
        """Start the bot — PTB manages the event loop entirely"""
        if settings.USE_WEBHOOK:
            self.application.run_webhook(
                listen="0.0.0.0",
                port=settings.WEBHOOK_PORT,
                url_path=settings.BOT_TOKEN,
                webhook_url=f"{settings.WEBHOOK_URL}/{settings.BOT_TOKEN}",
            )
        else:
            self.application.run_polling(
                allowed_updates=None,
                drop_pending_updates=False,
            )


if __name__ == '__main__':
    Bot().run()
