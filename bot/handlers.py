# fx/bot/handlers.py
import logging
from datetime import datetime
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import CallbackContext
from sqlalchemy.orm import Session

from database.repositories import UserRepository, TradeRepository
from database.models import SignalReceipt
from services.notification import NotificationService
from services.subscription import SubscriptionService
from services.results import ResultsService
from services.news_protection import NewsProtectionService
from services.ai_assistant import answer as assistant_answer
from utils.formatters import format_balance, format_positions, format_trade_history
from config.settings import settings

logger = logging.getLogger(__name__)


class CommandHandlers:
    """
    Basic command handlers (start, help, balance, etc.)
    """
    
    def __init__(self, db_session: Session, bot, mt5_manager=None):
        self.db = db_session
        self.bot = bot
        self.mt5_manager = mt5_manager
        self.user_repo = UserRepository(db_session)
        self.trade_repo = TradeRepository(db_session)
        self.notification = NotificationService(db_session, bot)
        self.sub_service = SubscriptionService(db_session)
    
    async def start(self, update: Update, context: CallbackContext):
        """Handle /start command"""
        user = update.effective_user
        db_user = self.user_repo.get_by_telegram_id(user.id)
        is_admin = user.id in settings.ADMIN_USER_IDS
        user_data = getattr(context, "user_data", {})
        from bot.referrals import parse_referral_payload

        if not db_user:
            referrer_id = parse_referral_payload(getattr(context, "args", ()), user.id)
            if referrer_id is not None:
                # Keep the first valid referral across repeated /start links.
                user_data.setdefault("pending_referrer_telegram_id", referrer_id)
        
        if db_user:
            _mode_badge = "🟢 LIVE TRADING" if (getattr(db_user, "trading_mode", None) or "demo") == "live" else "🔵 DEMO TRADING"
            _connection = "متصل" if getattr(db_user, "has_gateway_credentials", False) and getattr(db_user, "mt_connected", False) else "غير متصل"
            _mode_badge = "🔵 DRY RUN" if getattr(settings, "TRADING_DRY_RUN", True) else _mode_badge
            message = (
                f"👋 أهلًا بعودتك، {user.first_name}!\n\n"
                f"{_mode_badge}\n\n"
                f"حساب MT5 الخاص بك ({db_user.mt5_account_id or 'غير مربوط'}): {_connection}.\n"
                f"الخطة: *{db_user.subscription_tier.upper()}*\n\n"
                "ما الذي ترغب في فعله؟\n"
                "• /account - حالة الحساب\n"
                "• /subscription - حالة وخطط الاشتراك\n"
                "• /status - الحالة الحالية\n"
                "• /trades - سجل الصفقات\n"
                "• /trade - إرسال إشارة للتدفق الآمن\n"
                "• /balance - عرض الرصيد\n"
                "• /positions - عرض الصفقات المفتوحة\n"
                "• /settings - ضبط الإعدادات"
            )
            
            if is_admin:
            	message += (
            	    "\n\n*👑 أوامر المشرف:*\n"
            	    "• /admin - لوحة المشرف\n"
            	    "• /stats - إحصاءات النظام\n"
            	    "• /broadcast - إرسال رسالة للمستخدمين"
            	)
            	
        else:
            message = (
                "👋 *أهلًا بك في Tonpo Bot!*\n\n"
                "Tonpo يتحقق من الإشارة والمخاطر ويحميك من ظروف الأخبار قبل أي قرار تنفيذ.\n\n"
                "🎁 الحسابات الجديدة المؤهلة تبدأ تجربة مجانية لمدة 3 أيام من الخادم.\n"
                "1) استخدم /register لربط MT5\n"
                "2) راجع /status و /subscription\n"
                "3) تابع /signals و /results\n"
                "4) اسأل /assistant عن أي خطوة\n\n"
                "لا توجد وعود أرباح، والمساعد لا ينفذ صفقات."
            )

            if user_data.get("pending_referrer_telegram_id"):
                message += "\n\nتم فتح رابط إحالة؛ سيُحفظ مصدره عند إكمال التسجيل."
            
            if is_admin:
            	message += (
            	    "\n\n*👑 لديك صلاحية المشرف.*\n"
            	    "استخدم /admin لفتح لوحة المشرف (لا يلزم التسجيل)."
            	)
        
        from bot.keyboards import get_mini_app_keyboard
        await update.message.reply_text(
            message,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_mini_app_keyboard(),
        )
    
    async def help(self, update: Update, context: CallbackContext):
        """Handle /help command"""
        help_text = (
            "*📚 أوامر Tonpo Bot*\n\n"
            "*البدء:*\n"
            "/register - ربط حساب MT5\n"
            "/settings - ضبط تفضيلاتك\n\n"
            
            "*التداول:*\n"
            "/trade - إنشاء صفقة\n"
            "/calculate - حساب المخاطر دون تنفيذ صفقة\n"
            "/balance - عرض رصيد الحساب\n"
            "/positions - عرض الصفقات المفتوحة\n"
            "/history - عرض سجل الصفقات\n\n"
            
            "*الحساب:*\n"
            "/profile - عرض ملفك الشخصي\n"
            "/account - حالة الحساب\n"
            "/status - حالة الاتصال والتداول\n"
            "/trades - سجل الصفقات\n"
            "/signals - قرارات الإشارات\n"
            "/results - مركز النتائج\n"
            "/news - حالة حماية الأخبار\n"
            "/subscription - حالة وخطط الاشتراك\n"
            "/upgrade - ترقية الاشتراك\n"
            "/referral - الحصول على رابط الإحالة\n\n"
            
            "*الدعم:*\n"
            "/help - عرض هذه الرسالة\n"
            "/about - معلومات عن البوت\n"
            "\n"
            
            "*تنسيق الصفقة:*\n"
            "```\n"
            "BUY/SELL [LIMIT/STOP] SYMBOL\n"
            "Entry PRICE أو NOW\n"
            "SL PRICE\n"
            "TP1 PRICE\n"
            "TP2 PRICE (اختياري)\n"
            "```\n\n"
            
            "مثال:\n"
            "```\n"
            "BUY GBPUSD\n"
            "Entry NOW\n"
            "SL 1.25000\n"
            "TP 1.26000\n"
            "```"
        )
        
        # Add admin commands if user is admin
        if update.effective_user.id in settings.ADMIN_USER_IDS:
            help_text += (
                "\n*👑 أوامر المشرف:*\n"
                "/admin - لوحة المشرف\n"
                "/stats - إحصاءات النظام\n"
                "/broadcast <message> - إرسال رسالة للمستخدمين\n"
            )
        
        await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)
        
    async def assistant(self, update: Update, context: CallbackContext):
        """Answer product questions with the current user's safe context."""
        user = self.user_repo.get_by_telegram_id(update.effective_user.id)
        question = " ".join(getattr(context, "args", []) or []).strip() or "كيف أبدأ؟"
        result = assistant_answer(question, db=self.db, user=user, lang=getattr(user, "language_code", None) if user else None)
        await update.message.reply_text(result["reply"])

    async def about(self, update: Update, context: CallbackContext):
        """Handle /about command"""
        about_text = (
            "*🤖 حول Tonpo Bot*\n\n"
            "الإصدار: 2.0.0\n"
            "الترخيص: خاص\n\n"
            
            "*المزايا:*\n"
            "• تنفيذ آلي للصفقات\n"
            "• إدارة ذكية للمخاطر\n"
            "• عدة مستويات لجني الأرباح\n"
            "• إشعارات فورية\n"
            "• تحليلات متقدمة\n\n"
            
            "*الوسطاء المدعومون:*\n"
            "أي وسيط يدعم MetaTrader 5\n\n"
            
            "*الدعم:*\n"
            "انضم إلى مجتمعنا @fx_signal_copier"
        )
        
        await update.message.reply_text(about_text, parse_mode=ParseMode.MARKDOWN)
    
    async def balance(self, update: Update, context: CallbackContext):
        """Handle /balance command"""
        user_id = update.effective_user.id
        
        # This will be handled by the trading handler with MT5 connection
        context.user_data['action'] = 'balance'
        return await self._forward_to_trading(update, context)
    
    async def positions(self, update: Update, context: CallbackContext):
        """Handle /positions command"""
        user_id = update.effective_user.id
        
        context.user_data['action'] = 'positions'
        return await self._forward_to_trading(update, context)
    
    async def history(self, update: Update, context: CallbackContext):
        """Handle /history command"""
        user_id = update.effective_user.id
        db_user = self.user_repo.get_by_telegram_id(user_id)
        
        if not db_user:
            await update.message.reply_text("يرجى التسجيل أولًا باستخدام /register")
            return
        
        trades = self.trade_repo.get_user_trades(db_user.id, limit=20)
        
        if not trades:
            await update.message.reply_text("لا يوجد سجل للصفقات.")
            return
        
        history_text = format_trade_history(trades)
        await update.message.reply_text(history_text, parse_mode=ParseMode.HTML)
    
    async def profile(self, update: Update, context: CallbackContext):
        """Handle /profile command"""
        user_id = update.effective_user.id
        db_user = self.user_repo.get_by_telegram_id(user_id)
        
        if not db_user:
            await update.message.reply_text(
                "*👤 الملف الشخصي*\n\n"
                f"معرّف Telegram: `{user_id}`\n"
                "اسم المستخدم: "
                f"@{update.effective_user.username or 'غير متاح'}\n"
                "حساب MT5: غير مربوط\n"
                "الخطة: *FREE*\n\n"
                "يمكنك استخدام /register لربط حساب MT5 عند الحاجة.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        
        # Get subscription info
        plan = self.sub_service.get_user_plan(user_id)
        usage = self.sub_service.get_usage_stats(user_id)
        
        profile_text = (
            f"*👤 الملف الشخصي*\n\n"
            f"معرّف Telegram: `{db_user.telegram_id}`\n"
            f"اسم المستخدم: @{db_user.telegram_username or 'غير متاح'}\n"
            f"تاريخ الانضمام: {db_user.created_at.strftime('%Y-%m-%d')}\n\n"
            
            f"*حساب MT5:*\n"
            f"الحساب: `{db_user.mt5_account_id}`\n"
            f"الخادم: {db_user.mt5_server}\n"
            f"الحالة: {'✅ متصل' if db_user.mt_connected else '❌ غير متصل'}\n\n"
            
            f"*الاشتراك:*\n"
            f"الخطة: *{db_user.subscription_tier.upper()}*\n"
            f"صفقات اليوم: {usage.get('trades_today', 0)}/{plan.max_trades_per_day}\n"
            f"ينتهي في: {db_user.subscription_expiry.strftime('%Y-%m-%d') if db_user.subscription_expiry else 'غير محدد'}\n\n"
            
            f"*الإحصاءات:*\n"
            f"إجمالي الصفقات: {db_user.total_trades}\n"
            f"إجمالي الحجم: {db_user.total_volume:.2f}\n"
            f"نسبة الصفقات الرابحة: {db_user.win_rate:.1f}%\n"
        )
        
        await update.message.reply_text(profile_text, parse_mode=ParseMode.MARKDOWN)

    async def account(self, update: Update, context: CallbackContext):
        """Alias for the account overview used by the product command menu."""
        return await self.profile(update, context)

    async def subscription(self, update: Update, context: CallbackContext):
        """Show the existing subscription plans and current plan marker."""
        return await self.upgrade(update, context)

    async def status(self, update: Update, context: CallbackContext):
        """Show a safe, backend-authoritative status snapshot."""
        user = self.user_repo.get_by_telegram_id(update.effective_user.id)
        if not user:
            await update.message.reply_text("لم يتم التسجيل بعد. استخدم /register للبدء.")
            return
        dry_run = bool(getattr(settings, "TRADING_DRY_RUN", True))
        connection = "متصل" if user.has_gateway_credentials and user.mt_connected else "غير متصل"
        expiry = user.subscription_expiry.strftime("%Y-%m-%d") if user.subscription_expiry else "غير محدد"
        trial = "غير نشط"
        if user.trial_end and user.trial_end > datetime.utcnow():
            trial = f"نشط — متبقٍ {(user.trial_end - datetime.utcnow()).days} يوم"
        news = NewsProtectionService().system_status()
        news_label = {"inactive": "SAFE", "active": "PROTECTED", "stale": "STALE", "unavailable": "UNAVAILABLE"}.get(news.get("status"), "غير متاح")
        await update.message.reply_text(
            "📊 حالة Tonpo\n\n"
            f"DRY RUN: {'مفعّل — لا أوامر حقيقية' if dry_run else 'غير مفعّل'}\n"
            f"MT5: {connection}\n"
            f"الخطة: {user.subscription_tier.upper()} · تنتهي: {expiry}\n"
            f"Trial: {trial}\n"
            f"News Protection: {news_label}\n"
            f"{news.get('reason', 'لا توجد تفاصيل إضافية.')}",
        )

    async def trades(self, update: Update, context: CallbackContext):
        """Alias for the existing history command."""
        return await self.history(update, context)

    async def results(self, update: Update, context: CallbackContext):
        """Show real closed-trade results; never fabricate an empty account."""
        result = ResultsService(self.db).results(update.effective_user.id, "30d")
        if not result.get("has_data") and not result.get("has_signals"):
            await update.message.reply_text("📊 لا توجد بيانات للفترة المحددة. ستظهر الإشارات والصفقات الفعلية هنا.")
            return
        metrics = result["metrics"]
        today = ResultsService(self.db).activity(update.effective_user.id)
        await update.message.reply_text(
            "📊 *مركز النتائج — آخر 30 يومًا*\n\n"
            f"الصفقات المغلقة: {metrics['total_closed_trades']}\n"
            f"الرابحة/الخاسرة: {metrics['winning_trades']} / {metrics['losing_trades']}\n"
            f"نسبة الفوز: {metrics['win_rate']}%\n"
            f"إجمالي P/L: {metrics['total_pnl']}\n"
            f"أقصى تراجع: {metrics['max_drawdown'] if metrics['max_drawdown'] is not None else '—'}\n\n"
            f"اليوم: {today.get('signals_received', 0)} إشارة، المقبول {today.get('signals_accepted', 0)}، المرفوض {today.get('signals_rejected', 0)}، P/L {today.get('pnl', 0)}",
            parse_mode=ParseMode.MARKDOWN,
        )

    async def signals(self, update: Update, context: CallbackContext):
        """Show recent persisted signal decisions and explain only known reasons."""
        user = self.user_repo.get_by_telegram_id(update.effective_user.id)
        if not user:
            await update.message.reply_text("لم يتم التسجيل بعد. استخدم /register للبدء.")
            return
        rows = self.db.query(SignalReceipt).filter(SignalReceipt.user_id == user.id).order_by(SignalReceipt.created_at.desc()).limit(10).all()
        if not rows:
            await update.message.reply_text("📡 لا توجد إشارات بعد. ستظهر أول إشارة مع قرارها هنا.")
            return
        lines = ["📡 آخر قرارات الإشارات"]
        for row in rows:
            stamp = row.created_at.strftime('%Y-%m-%d %H:%M') if row.created_at else '—'
            reason = f"\n  السبب: {row.rejection_reason}" if row.rejection_reason else ""
            lines.append(f"• {row.status} · {stamp}{reason}")
        await update.message.reply_text("\n".join(lines))

    async def news(self, update: Update, context: CallbackContext):
        """Report the backend news-protection state without making a decision in Telegram."""
        result = NewsProtectionService().system_status()
        labels = {"inactive": "SAFE", "active": "PROTECTED", "unavailable": "STALE / UNAVAILABLE", "stale": "STALE / UNAVAILABLE"}
        label = labels.get(result.get("status"), "غير متاح")
        await update.message.reply_text(
            f"📰 News Protection: {label}\n"
            f"{result.get('reason', 'لا توجد بيانات مؤكدة.')}"
            + (f"\nحتى: {result['protection_until']}" if result.get('protection_until') else "")
        )

    async def upgrade(self, update: Update, context: CallbackContext):
        """Handle /upgrade command — shows plans dynamically from database"""
        from bot.keyboards import get_plans_keyboard
        
        # Get user's current plan
        user_id = update.effective_user.id
        user = self.user_repo.get_by_telegram_id(user_id)
        current_tier = user.subscription_tier if user else 'free'
        
        # Fetch all plans from database
        plans = self.sub_service.get_all_plans()
        
        if not plans:
            await update.message.reply_text(
                "❌ لا تتوفر خطط اشتراك حاليًا. يرجى التواصل مع الدعم."
            )
            return
        
        # Sort plans by price
        plans.sort(key=lambda p: float(p.price_monthly))
        
        # Build dynamic plan display
        text = "*📊 خطط الاشتراك*\n\n"
        
        for plan in plans:
            # Current plan indicator
            current = " ← *خطتك الحالية*" if plan.tier == current_tier else ""
            
            # Price display
            if plan.is_free:
                price_str = "مجانية"
            else:
                price_str = f"${plan.price_monthly}/month · ${plan.price_yearly}/year"
            
            text += f"*خطة {plan.name}*{current}\n"
            text += f"💰 {price_str}\n"
            text += f"• {plan.max_trades_per_day} صفقة يوميًا كحد أقصى\n"
            text += f"• الحد الأقصى لحجم الصفقة: {plan.max_position_size}\n"
            
            if plan.supports_multiple_tps:
                text += "• ✅ عدة مستويات لجني الأرباح\n"
            if plan.supports_auto_trading:
                text += "• ✅ التداول الآلي\n"
            if plan.supports_api:
                text += "• ✅ الوصول إلى API\n"
            if plan.max_connections > 1:
                text += f"• {plan.max_connections} حسابات MT5\n"
            if plan.support_priority == 'high':
                text += "• ⚡ دعم بأولوية\n"
            
            text += "\n"
        
        # Add expiry info if user has paid plan
        if user and user.subscription_expiry and current_tier != 'free':
            from datetime import datetime
            days_left = (user.subscription_expiry - datetime.utcnow()).days
            if days_left > 0:
                text += f"_تنتهي خطة {current_tier.title()} خلال {days_left} يومًا_\n\n"
            else:
                text += "_⚠️ انتهت صلاحية خطتك_\n\n"
        
        text += "اختر خطة لعرض تفاصيلها:"
        
        await update.message.reply_text(
            text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_plans_keyboard()
        )

    async def referral(self, update: Update, context: CallbackContext):
        """Send a referral link based on the current Telegram bot identity."""
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        from bot.referrals import build_referral_link

        link = await build_referral_link(context.bot, update.effective_user.id)
        await update.message.reply_text(
            f"رابط الإحالة الخاص بك:\n{link}\n\n"
            "يُسجّل مصدر الإحالة عند إكمال المستخدم الجديد للتسجيل.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("مشاركة رابط الإحالة", url=link)
            ]]),
        )
    
    async def unknown(self, update: Update, context: CallbackContext):
        """Handle unknown commands"""
        await update.message.reply_text(
            "❌ أمر غير معروف. استخدم /help لعرض الأوامر المتاحة."
        )
    
    async def _forward_to_trading(self, update: Update, context: CallbackContext):
        """Forward to trading handler for MT5 operations"""
        from bot.trading import TradingHandler
        
        handler = TradingHandler(self.db, self.bot, mt5_manager=self.mt5_manager)
        return await handler.handle_action(update, context)
