# fx/bot/callbacks.py
import logging
from typing import Dict, Any, Optional
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import CallbackContext
from sqlalchemy.orm import Session

from database.repositories import UserRepository, TradeRepository
from services.notification import NotificationService
from services.subscription import SubscriptionService
from bot.keyboards import (
    get_settings_keyboard, get_plans_keyboard,
    get_confirmation_keyboard, get_pagination_keyboard
)
from bot.message_utils import safe_edit_message
from config.settings import settings

logger = logging.getLogger(__name__)


class CallbackHandlers:
    """
    Handles all callback queries from inline keyboards
    """
    
    def __init__(self, db_session: Session, bot, execution_provider=None):
        self.db = db_session
        self.bot = bot
        self.user_repo = UserRepository(db_session)
        self.trade_repo = TradeRepository(db_session)
        self.notification = NotificationService(db_session, bot)
        self.sub_service = SubscriptionService(db_session)
        self.execution_provider = execution_provider
        
        # Register handlers
        self.handlers = {
            'plan': self.handle_plan,
            'notification': self.handle_notification,
            'trade': self.handle_trade_action,
            'position': self.handle_position,
            'pagination': self.handle_pagination,
            'confirm': self.handle_confirmation,
            'help': self.handle_help,
        }
    
    async def handle(self, update: Update, context: CallbackContext) -> None:
        """
        Main callback handler - routes to appropriate sub-handler
        """
        query = update.callback_query
        await query.answer()
        
        data = query.data
        if not data:
            return
        
        # Parse callback data format: "handler:action:data"
        parts = data.split(':')
        handler_name = parts[0]
        
        # Find and execute handler
        handler = self.handlers.get(handler_name)
        if handler:
            await handler(update, context, parts[1:])
        else:
            logger.warning(f"No handler for callback: {data}")
            await query.edit_message_text("إجراء غير معروف.")
    
    async def handle_plan(self, update: Update, context: CallbackContext, args: list):
        """Handle subscription plan callbacks"""
        query = update.callback_query
        action = args[0] if args else 'list'
        
        if action == 'list':
            # Show plan list
            plans = self.sub_service.get_all_plans()
            
            text = "*📊 خطط الاشتراك*\n\n"
            for plan in plans:
                text += (
                    f"*{plan.name}*\n"
                    f"• ${plan.price_monthly}/شهريًا\n"
                    f"• {plan.max_trades_per_day} صفقة يوميًا\n"
                    f"• الحد الأقصى للحجم: {plan.max_position_size} لوت\n"
                    f"• عدة مستويات لجني الأرباح: {'✅' if plan.supports_multiple_tps else '❌'}\n"
                    f"• التداول الآلي: {'✅' if plan.supports_auto_trading else '❌'}\n\n"
                )
            
            await safe_edit_message(
                query,
                text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=get_plans_keyboard()
            )
        
        elif action == 'select':
            # Show specific plan details
            plan_tier = args[1]
            plan = self.sub_service.get_plan(plan_tier)
            
            if not plan:
                await query.edit_message_text("❌ لم يتم العثور على الخطة.")
                return
            
            user_id = update.effective_user.id
            registered_user = self.user_repo.get_by_telegram_id(user_id)
            current_plan = self.sub_service.get_user_plan(user_id) if registered_user else None
            
            text = (
                f"*{plan.name} Plan*\n\n"
                f"السعر: ${plan.price_monthly}/شهريًا أو ${plan.price_yearly}/سنويًا\n\n"
                f"*المزايا:*\n"
                f"• {plan.max_trades_per_day} صفقة يوميًا\n"
                f"• الحد الأقصى لحجم الصفقة: {plan.max_position_size}\n"
                f"• عدة مستويات لجني الأرباح: {'✅' if plan.supports_multiple_tps else '❌'}\n"
                f"• التداول الآلي: {'✅' if plan.supports_auto_trading else '❌'}\n"
                f"• الوصول إلى API: {'✅' if plan.supports_api else '❌'}\n"
                f"• أولوية الدعم: {plan.support_priority}\n\n"
            )
            
            if plan.features:
                text += "*مزايا إضافية:*\n"
                for feature in plan.features:
                    text += f"• {feature}\n"
            
            if current_plan and current_plan.tier == plan_tier:
                text += "\n✅ *هذه خطتك الحالية*"
                keyboard = None
            else:
                from bot.keyboards import get_upgrade_keyboard
                keyboard = get_upgrade_keyboard(plan_tier)
            
            await safe_edit_message(
                query,
                text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard
            )
    
    async def handle_notification(self, update: Update, context: CallbackContext, args: list):
        """Handle notification callbacks"""
        query = update.callback_query
        action = args[0]
        
        user_id = update.effective_user.id
        settings = self.user_repo.get_by_telegram_id(user_id).settings
        
        if action == 'mark_read':
            # Mark all as read
            from database.repositories import NotificationRepository
            repo = NotificationRepository(self.db)
            count = repo.mark_all_as_read(user_id)
            
            await query.edit_message_text(f"✅ تم تحديد {count} إشعارًا كمقروء.")
        
        elif action == 'view':
            # View specific notification
            notif_id = int(args[1])
            from database.models import Notification
            
            notif = self.db.query(Notification).filter(
                Notification.id == notif_id,
                Notification.user_id == user_id
            ).first()
            
            if notif:
                # Mark as read
                notif.is_read = True
                self.db.commit()
                
                text = (
                    f"*{notif.title}*\n\n"
                    f"{notif.message}\n\n"
                    f"_{notif.created_at.strftime('%Y-%m-%d %H:%M UTC')}_"
                )
                
                await query.edit_message_text(
                    text,
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await query.edit_message_text("❌ لم يتم العثور على الإشعار.")
        
        elif action == 'clear':
            # Clear all notifications
            count = self.db.query(Notification).filter(
                Notification.user_id == user_id
            ).delete()
            self.db.commit()
            
            await query.edit_message_text(f"✅ تم حذف {count} إشعارًا.")
    
    async def handle_trade_action(self, update: Update, context: CallbackContext, args: list):
        """Handle trade-related callbacks"""
        query = update.callback_query
        action = args[0]
        
        if action == 'close':
            # Close a position
            position_id = args[1]
            
            from services.trade_executor import TradeExecutor
            executor = TradeExecutor(
                self.db,
                self.bot,
                execution_provider=self.execution_provider,
            )
            
            result = await executor.close_trade(update.effective_user.id, position_id)
            
            if result['success']:
                await query.edit_message_text(f"✅ تم إغلاق الصفقة {position_id}.")
            else:
                await query.edit_message_text(f"❌ تعذر الإغلاق: {result['error']}")
        
        elif action == 'modify':
            # Modify position
            position_id = args[1]
            
            # Store in context for modification flow
            context.user_data['modify_position'] = position_id
            
            await query.edit_message_text(
                "أدخل سعري وقف الخسارة وجني الأرباح الجديدين:\n"
                "التنسيق: `SL PRICE TP PRICE`\n"
                "مثال: `1.25000 1.26000`"
            )
        
        elif action == 'history':
            # View trade history
            page = int(args[1]) if len(args) > 1 else 1
            user_id = update.effective_user.id
            db_user = self.user_repo.get_by_telegram_id(user_id)
            
            trades = self.trade_repo.get_user_trades(db_user.id, limit=10, offset=(page-1)*10)
            total = self.trade_repo.get_user_trades(db_user.id, limit=10000).__len__()
            total_pages = (total + 9) // 10
            
            if not trades:
                await query.edit_message_text("لا يوجد سجل للصفقات.")
                return
            
            text = "*📊 Trade History*\n\n"
            for trade in trades[:10]:
                profit_icon = "✅" if trade.profit_loss and trade.profit_loss > 0 else "❌" if trade.profit_loss and trade.profit_loss < 0 else "⏳"
                text += (
                    f"{profit_icon} {trade.order_type} {trade.symbol}\n"
                    f"   Size: {trade.position_size} | Status: {trade.status}\n"
                    f"   {trade.created_at.strftime('%Y-%m-%d %H:%M')}\n\n"
                )
            
            await query.edit_message_text(
                text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=get_pagination_keyboard(page, total_pages, 'trade_history')
            )
    
    async def handle_position(self, update: Update, context: CallbackContext, args: list):
        """Handle position-related callbacks"""
        query = update.callback_query
        action = args[0]
        
        if action == 'view':
            # View position details
            position_id = args[1]
            
            try:
                db_user = self.user_repo.get_by_telegram_id(update.effective_user.id)
                if not db_user or not db_user.has_gateway_credentials:
                    await query.edit_message_text("❌ الحساب غير متصل. استخدم /register أولًا.")
                    return
                
                if not self.execution_provider:
                    raise RuntimeError("Trading gateway is unavailable")
                connection = await self.execution_provider.get_connection(update.effective_user.id)
                positions = await connection.get_positions()
                position = next((p for p in positions if str(p['id']) == str(position_id)), None)
                if position:
                    text = (
                        f"*تفاصيل الصفقة*\n\n"
                        f"المعرّف: `{position['id']}`\n"
                        f"الرمز: {position['symbol']}\n"
                        f"النوع: {position['type']}\n"
                        f"الحجم: {position['volume']}\n"
                        f"سعر الفتح: {position['openPrice']}\n"
                        f"السعر الحالي: {position['currentPrice']}\n"
                        f"SL: {position['stopLoss']}\n"
                        f"TP: {position['takeProfit']}\n"
                        f"الربح: {position['profit']}\n"
                        f"رسوم التبييت: {position['swap']}\n"
                    )
                    
                    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN)
                else:
                    await query.edit_message_text("❌ لم يتم العثور على الصفقة.")
                    
            except Exception as e:
                await query.edit_message_text("❌ تعذر تنفيذ الإجراء. يرجى المحاولة لاحقًا.")
        
        elif action == 'close_all':
            db_user = self.user_repo.get_by_telegram_id(update.effective_user.id)
            if (not db_user or not db_user.is_verified or not db_user.is_active
                    or db_user.is_banned):
                await query.edit_message_text("❌ الحساب غير مصرح له بهذا الإجراء.")
                return
            if not db_user.has_gateway_credentials or not self.execution_provider:
                await query.edit_message_text("❌ الحساب غير متصل. استخدم /register أولًا.")
                return

            # Close all positions
            from bot.keyboards import get_confirmation_keyboard
            
            await query.edit_message_text(
                "هل أنت متأكد من رغبتك في إغلاق جميع الصفقات؟",
                reply_markup=get_confirmation_keyboard('close_all_positions')
            )
    
    async def handle_pagination(self, update: Update, context: CallbackContext, args: list):
        """Handle pagination callbacks"""
        query = update.callback_query
        pagination_type = args[0]
        page = int(args[1])
        
        if pagination_type == 'trade_history':
            # Forward to trade history with new page
            await self.handle_trade_action(update, context, ['history', str(page)])
        
        elif pagination_type == 'notifications':
            # Show notifications page
            user_id = update.effective_user.id
            from database.repositories import NotificationRepository
            
            repo = NotificationRepository(self.db)
            notifications = repo.get_unread(user_id)
            
            # Paginate
            start = (page - 1) * 5
            end = start + 5
            page_notifs = notifications[start:end]
            total_pages = (len(notifications) + 4) // 5
            
            if not page_notifs:
                await query.edit_message_text("لا توجد إشعارات.")
                return
            
            text = "*🔔 Notifications*\n\n"
            for notif in page_notifs:
                icon = "🆕" if not notif.is_read else "📌"
                text += f"{icon} {notif.title}\n"
                text += f"   {notif.created_at.strftime('%H:%M')} - {notif.message[:50]}...\n\n"
            
            await safe_edit_message(
                query,
                text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=get_pagination_keyboard(page, total_pages, 'notifications')
            )
    
    async def handle_confirmation(self, update: Update, context: CallbackContext, args: list):
        """Handle confirmation callbacks"""
        query = update.callback_query
        action = args[0]
        confirmed = args[1] == 'yes'
        
        if not confirmed:
            await query.edit_message_text("❌ تم إلغاء الإجراء.")
            return
        
        # Process confirmed actions
        if action == 'close_all_positions':
            if getattr(settings, 'TRADING_DRY_RUN', False):
                await query.edit_message_text("❌ التداول معطل في وضع المحاكاة.")
                return
            # Close all positions
            # Get all positions
            try:
                db_user = self.user_repo.get_by_telegram_id(update.effective_user.id)
                if (not db_user or not db_user.is_verified or not db_user.is_active
                        or db_user.is_banned):
                    await query.edit_message_text("❌ الحساب غير مصرح له بهذا الإجراء.")
                    return
                if not db_user.has_gateway_credentials:
                    await query.edit_message_text("❌ الحساب غير متصل. استخدم /register أولًا.")
                    return
                
                if not self.execution_provider:
                    raise RuntimeError("Trading gateway is unavailable")
                connection = await self.execution_provider.get_connection(update.effective_user.id)
                positions = await connection.get_positions()
                
                closed = 0
                failed = 0
                
                for position in positions:
                    try:
                        if await connection.close_position(str(position['id'])):
                            closed += 1
                        else:
                            failed += 1
                    except:
                        failed += 1
                
                await query.edit_message_text(
                    f"✅ أُغلقت {closed} صفقات. تعذر إغلاق: {failed}"
                )
                
            except Exception as e:
                await query.edit_message_text("❌ تعذر تنفيذ الإجراء. يرجى المحاولة لاحقًا.")
        
        elif action == 'delete_account':
            # Delete user account
            user_id = update.effective_user.id
            self.user_repo.delete_user(user_id)
            
            await query.edit_message_text(
                "✅ تم حذف حسابك.\n"
                "يسعدنا عودتك؛ استخدم /register إذا غيرت رأيك."
            )
    
    async def handle_help(self, update: Update, context: CallbackContext, args: list):
        """Handle help section callbacks"""
        query = update.callback_query
        section = args[0] if args else 'main'
        
        help_texts = {
            'main': (
                "*📚 مركز المساعدة*\n\n"
                "اختر موضوعًا من الأسفل:"
            ),
            'trading': (
                "*📈 مساعدة التداول*\n\n"
                "لإنشاء صفقة، استخدم:\n"
                "`/trade`\n\n"
                "التنسيق:\n"
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
            ),
            'risk': (
                "*⚖️ إدارة المخاطر*\n\n"
                "يحسب البوت حجم الصفقة استنادًا إلى:\n"
                "• رصيد الحساب\n"
                "• وقف الخسارة بالنقاط\n"
                "• نسبة المخاطرة التي تحددها\n\n"
                "المعادلة: `(الرصيد × نسبة المخاطرة) ÷ (نقاط SL × $10)`\n\n"
                "اضبط نسبة المخاطرة من /settings"
            ),
            'subscription': (
                "*💎 خطط الاشتراك*\n\n"
                "• مجانية: 10 صفقات يوميًا\n"
                "• أساسية: 50 صفقة يوميًا وعدة مستويات لجني الأرباح\n"
                "• احترافية: 200 صفقة يوميًا وتداول آلي\n"
                "• مؤسسات: غير محدودة\n\n"
                "استخدم /upgrade لعرض الخطط"
            ),
            'api': (
                "*🔌 الوصول إلى API*\n\n"
                "أنشئ مفتاح API من /settings لاستخدام البوت برمجيًا.\n\n"
                "أرسل المفتاح ضمن الترويسات:\n"
                "`X-API-Key: your-key-here`"
            )
        }
        
        text = help_texts.get(section, help_texts['main'])
        
        from bot.keyboards import get_help_keyboard
        await query.edit_message_text(
            text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_help_keyboard(section)
        )
