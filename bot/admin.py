# fx/bot/admin.py
import asyncio
import logging
from datetime import datetime, timedelta
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ConversationHandler, CallbackContext, CallbackQueryHandler, MessageHandler, filters
from sqlalchemy.orm import Session
from sqlalchemy import func

from database.repositories import UserRepository, TradeRepository
from database.models import (
    AdminAuditLog, AdminOffer, AdminRole, AdminSetting, ConnectionLog,
    Notification, SubscriptionPlan, SupportMessage, SupportTicket, Trade, User,
)
from services.notification import NotificationService
from services.analytics import AnalyticsService
from services.monitoring import MonitoringService
from config.settings import settings
from bot.keyboards import (
    get_admin_keyboard,
    get_admin_user_actions_keyboard,
    get_admin_user_keyboard,
    get_confirmation_keyboard,
    get_admin_section_keyboard,
    get_admin_emergency_keyboard,
    get_admin_plans_keyboard,
)
from bot.message_utils import safe_edit_message

logger = logging.getLogger(__name__)

ROLE_PERMISSIONS = {
    "SUPER_ADMIN": {"*"},
    "ADMIN": {
        "users.view", "users.manage", "plans.view", "plans.manage",
        "subscriptions.view", "subscriptions.manage", "trial.grant", "trial.revoke",
        "offers.view", "offers.manage", "support.view", "support.reply",
        "broadcast.send", "statistics.view", "settings.view", "settings.manage",
        "emergency_stop",
    },
    "SUPPORT": {"users.view", "support.view", "support.reply"},
    "MODERATOR": {"users.view", "users.manage", "support.view"},
    "ANALYST": {"statistics.view", "users.view", "plans.view", "subscriptions.view"},
}

# Conversation states
(ADMIN_MAIN, USER_MANAGEMENT, BROADCAST, SYSTEM_STATS, CONFIRM_ACTION, SUPPORT_REPLY) = range(6)

class AdminHandler:
    def __init__(self, db_session: Session, bot):
        self.db = db_session
        self.bot = bot
        self.user_repo = UserRepository(db_session)
        self.trade_repo = TradeRepository(db_session)
        self.notification = NotificationService(db_session, bot)
        self.analytics = AnalyticsService(db_session)
        self.monitoring = MonitoringService(db_session)
        
        # Admin user IDs from settings
        self.admin_ids = settings.ADMIN_USER_IDS
    
    def is_admin(self, user_id: int) -> bool:
        """Return whether the user has access to any admin console section."""
        return self.has_permission(user_id, "users.view")

    def role_for(self, user_id: int) -> str:
        if user_id in self.admin_ids:
            return "SUPER_ADMIN"
        # Fail closed when session was never bound (e.g. partial construction).
        if getattr(self, "db", None) is None:
            return ""
        try:
            assignment = self.db.query(AdminRole).filter_by(
                telegram_id=user_id, is_active=True
            ).first()
            return assignment.role if assignment else ""
        except Exception:
            try:
                self.db.rollback()
            except Exception:
                pass
            return ""

    def has_permission(self, user_id: int, permission: str) -> bool:
        role = self.role_for(user_id)
        if not role:
            return False
        if role == "SUPER_ADMIN":
            return True
        if getattr(self, "db", None) is None:
            return False
        try:
            assignment = self.db.query(AdminRole).filter_by(
                telegram_id=user_id, is_active=True
            ).first()
            explicit = set(assignment.permissions or []) if assignment else set()
        except Exception:
            try:
                self.db.rollback()
            except Exception:
                pass
            explicit = set()
        permissions = explicit or ROLE_PERMISSIONS.get(role, set())
        return "*" in permissions or permission in permissions

    def record_audit(self, admin_id: int, action: str, *, target_type=None,
                     target_id=None, old_value=None, new_value=None,
                     result="success", failure_reason=None) -> bool:
        """Persist a credential-free audit record; fail closed when unavailable."""
        entry = AdminAuditLog(
            admin_telegram_id=admin_id,
            role=self.role_for(admin_id) or "UNKNOWN",
            action=action,
            target_type=target_type,
            target_id=str(target_id)[:100] if target_id is not None else None,
            old_value=old_value,
            new_value=new_value,
            result=result,
            failure_reason=(str(failure_reason)[:200] if failure_reason else None),
        )
        try:
            self.db.add(entry)
            self.db.commit()
            return True
        except Exception as exc:
            self.db.rollback()
            logger.error("Admin audit write failed (%s)", type(exc).__name__)
            return False

    async def _require_admin(self, update: Update) -> bool:
        user = update.effective_user
        if user and self.is_admin(user.id):
            return True
        query = update.callback_query
        if query:
            await query.answer("❌ Admin access required", show_alert=True)
        elif update.effective_message:
            await update.effective_message.reply_text("❌ وصول غير مصرح به.")
        return False

    def _get_admin_counts(self):
        """Use aggregate queries so admin views do not load every model column."""
        cutoff = datetime.utcnow() - timedelta(hours=24)
        scalar = lambda query: query.scalar() or 0
        return {
            'users': scalar(self.db.query(func.count(User.id))),
            'active_users': scalar(self.db.query(func.count(User.id)).filter(User.is_active.is_(True))),
            'verified_users': scalar(self.db.query(func.count(User.id)).filter(User.is_verified.is_(True))),
            'subscriptions': {
                tier: scalar(self.db.query(func.count(User.id)).filter(User.subscription_tier == tier))
                for tier in ('free', 'basic', 'pro', 'enterprise')
            },
            'trades_today': scalar(self.db.query(func.count(Trade.id)).filter(Trade.created_at >= cutoff)),
            'trades_total': scalar(self.db.query(func.count(Trade.id))),
            'connections_today': scalar(self.db.query(func.count(ConnectionLog.id)).filter(ConnectionLog.created_at >= cutoff)),
            'successful_connections': scalar(self.db.query(func.count(ConnectionLog.id)).filter(
                ConnectionLog.created_at >= cutoff, ConnectionLog.status == 'success'
            )),
            'average_latency': scalar(self.db.query(func.avg(ConnectionLog.latency_ms)).filter(
                ConnectionLog.created_at >= cutoff, ConnectionLog.latency_ms.isnot(None)
            )),
        }

    @staticmethod
    def _metric_display(system_info, name, suffix='%'):
        value = (system_info.get(name) or {}).get('percent')
        return f"{value}{suffix}" if value is not None else "غير متاح"
    
    async def dashboard(self, update: Update, context: CallbackContext) -> int:
        """Show admin dashboard"""
        """Show admin dashboard (admin check done by wrap_admin middleware)"""
        if not await self._require_admin(update):
            return ConversationHandler.END
        
        # Get quick stats
        # Aggregate queries avoid loading newer Trade fields absent from older
        # deployed schemas.
        total_users = self.db.query(func.count(User.id)).filter(
            User.is_active.is_(True), User.is_verified.is_(True), User.is_banned.is_(False)
        ).scalar() or 0
        trades_today = self.db.query(func.count(Trade.id)).filter(
            Trade.created_at >= datetime.utcnow() - timedelta(hours=24)
        ).scalar() or 0
        system_health = self.monitoring.get_system_health()
        system_info = system_health.get('system') or {}
        cpu_display = self._metric_display(system_info, 'cpu')
        memory_display = self._metric_display(system_info, 'memory')
        
        dashboard_text = (
            "*👑 لوحة المشرف*\n\n"
            f"*حالة النظام:*\n"
            f"• الحالة: {system_health['status']}\n"
            f"• مدة التشغيل: {system_health['uptime']/3600:.1f} ساعة\n"
            f"• المعالج: {cpu_display}\n"
            f"• الذاكرة: {memory_display}\n\n"
            
            f"*الإحصاءات:*\n"
            f"• إجمالي المستخدمين: {total_users}\n"
            f"• الصفقات (24 ساعة): {trades_today}\n"
            f"• الاتصالات النشطة: {system_health['database'].get('active_connections', 0)}\n\n"
            
            "اختر أحد الخيارات:"
        )
        
        keyboard = get_admin_keyboard()
        if update.callback_query:
        	await update.callback_query.edit_message_text(
                dashboard_text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard
            )
        else:
            await update.message.reply_text(
                dashboard_text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard
            )
        
        return ADMIN_MAIN
        
    async def cancel(self, update: Update, context: CallbackContext) -> int:
    	"""Cancel admin conversation"""
    	await update.message.reply_text("👑 انتهت جلسة المشرف.")
    	context.user_data.pop('pending_action', None)
    	context.user_data.pop('selected_user', None)
    	return ConversationHandler.END
    
    async def handle_menu(self, update: Update, context: CallbackContext) -> int:
        """Handle admin menu selections"""
        if not await self._require_admin(update):
            return ConversationHandler.END
        query = update.callback_query
        await query.answer()
        
        action = query.data.replace('admin_', '')
        
        if action == 'users':
            return await self._show_user_management(update, context)
        elif action == 'broadcast':
            return await self._start_broadcast(update, context)
        elif action == 'stats':
            return await self._show_system_stats(update, context)
        elif action == 'alerts':
            return await self._show_alerts(update, context)
        elif action == 'back':
            return await self.dashboard(update, context)
        elif action == 'close':
            await query.edit_message_text("👑 انتهت جلسة المشرف.")
            return ConversationHandler.END
    
    async def _show_user_management(self, update: Update, context: CallbackContext) -> int:
        """Show user management interface"""
        query = update.callback_query
        
        # Get recent users
        users = self.user_repo.get_active_users(limit=10)
        
        user_list = "*إدارة المستخدمين*\n\n"
        for user in users:
            status = "✅" if user.is_active else "❌"
            verified = "✓" if user.is_verified else "✗"
            user_list += f"{status} {verified} {user.telegram_username or user.telegram_id} - {user.subscription_tier}\n"
        
        user_list += "\nاختر مستخدمًا لإدارته:"
        
        await safe_edit_message(
            query,
            user_list,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_admin_user_keyboard(users)
        )
        
        return USER_MANAGEMENT

    async def handle_admin_text(self, update: Update, context: CallbackContext) -> int:
        """Handle validated text input for the current admin conversation step."""
        if not await self._require_admin(update):
            return ConversationHandler.END
        state = context.user_data.pop('admin_waiting_for', None)
        value = (update.effective_message.text or '').strip()
        if state == 'user_search':
            user = self.user_repo.get_by_telegram_id(int(value)) if value.isdigit() else None
            if user is None and value:
                user = self.user_repo.get_by_username(value.lstrip('@'))
            if not user:
                await update.effective_message.reply_text(
                    "لم أعثر على مستخدم بهذا Telegram ID أو username. أعد المحاولة أو أرسل /cancel."
                )
                context.user_data['admin_waiting_for'] = 'user_search'
                return USER_MANAGEMENT
            context.user_data['selected_user'] = user.telegram_id
            await self._show_user_details(update, context)
            return USER_MANAGEMENT
        if state == 'user_message':
            if not value or len(value) > 4000:
                await update.effective_message.reply_text("الرسالة فارغة أو أطول من الحد المسموح.")
                context.user_data['admin_waiting_for'] = 'user_message'
                return USER_MANAGEMENT
            context.user_data['pending_message'] = value
            context.user_data['pending_action'] = 'user_message'
            await update.effective_message.reply_text(
                f"معاينة الرسالة إلى المستخدم {context.user_data.get('selected_user')}:\n\n"
                f"{value}\n\nهل تؤكد الإرسال؟",
                reply_markup=get_confirmation_keyboard(),
            )
            return CONFIRM_ACTION
        if state in {'plan_create', 'plan_edit'}:
            try:
                parts = [part.strip() for part in value.split('|')]
                if len(parts) != 8:
                    raise ValueError
                name, tier, monthly, yearly, trades, position, symbols, visible_order = parts
                visible_text, separator, order_text = visible_order.partition(',')
                if not separator:
                    raise ValueError
                monthly_value, yearly_value = float(monthly), float(yearly)
                trades_value, position_value = int(trades), float(position)
                symbols_value, order_value = int(symbols), int(order_text)
                if (not name or len(name) > 50 or not tier.isalnum() or len(tier) > 20
                        or monthly_value < 0 or yearly_value < 0 or trades_value < 0
                        or position_value <= 0 or symbols_value < 0
                        or visible_text.lower() not in {'true', 'false'}):
                    raise ValueError
                draft = {
                    'name': name, 'tier': tier.lower(), 'price_monthly': monthly_value,
                    'price_yearly': yearly_value, 'max_trades_per_day': trades_value,
                    'max_position_size': position_value, 'max_symbols': symbols_value,
                    'is_visible': visible_text.lower() == 'true', 'display_order': order_value,
                }
                if state == 'plan_create' and self.db.query(SubscriptionPlan.id).filter_by(tier=draft['tier']).first():
                    raise ValueError
            except Exception:
                self.db.rollback()
                await update.effective_message.reply_text(
                    "صيغة الباقة غير صالحة أو tier موجود. استخدم:\n"
                    "name|tier|price_monthly|price_yearly|max_trades_per_day|max_position_size|max_symbols|visible,order"
                )
                context.user_data['admin_waiting_for'] = state
                return ADMIN_MAIN
            context.user_data['pending_plan'] = draft
            context.user_data['pending_action'] = state
            await update.effective_message.reply_text(
                f"معاينة الباقة: {draft['name']} ({draft['tier']})\n"
                f"السعر الشهري/السنوي: {monthly_value}/{yearly_value}\n"
                "هل تؤكد الحفظ؟",
                reply_markup=get_confirmation_keyboard(),
            )
            return CONFIRM_ACTION
        if state == 'role_assignment':
            try:
                id_text, role = [part.strip() for part in value.split('|', 1)]
                telegram_id = int(id_text)
                role = role.upper()
                if telegram_id <= 0 or role not in {'ADMIN', 'SUPPORT', 'MODERATOR', 'ANALYST'}:
                    raise ValueError
                if telegram_id in self.admin_ids:
                    raise ValueError
            except (ValueError, TypeError):
                await update.effective_message.reply_text(
                    "صيغة غير صالحة. استخدم Telegram_ID|ADMIN أو SUPPORT أو MODERATOR أو ANALYST."
                )
                context.user_data['admin_waiting_for'] = 'role_assignment'
                return ADMIN_MAIN
            context.user_data['pending_role'] = {'telegram_id': telegram_id, 'role': role}
            context.user_data['pending_action'] = 'role_add'
            await update.effective_message.reply_text(
                f"تأكيد إضافة {role} للمعرّف {telegram_id} بصلاحيات الدور المحددة مسبقًا؟",
                reply_markup=get_confirmation_keyboard(),
            )
            return CONFIRM_ACTION
        if state in {'offer_create', 'offer_edit'}:
            try:
                parts = [part.strip() for part in value.split('|')]
                if len(parts) != 7:
                    raise ValueError
                title, tier, feature, max_uses_raw, ends_raw, target_raw, code = parts
                if not title or len(title) > 120 or len(feature) > 80:
                    raise ValueError
                tier = tier or None
                if tier and not self.db.query(SubscriptionPlan.id).filter_by(tier=tier).first():
                    raise ValueError
                max_uses = int(max_uses_raw) if max_uses_raw else None
                if max_uses is not None and max_uses < 1:
                    raise ValueError
                ends_at = datetime.fromisoformat(ends_raw) if ends_raw else None
                if ends_at and ends_at <= datetime.utcnow():
                    raise ValueError
                targets = [int(item.strip()) for item in target_raw.split(',') if item.strip()]
                if any(item <= 0 for item in targets):
                    raise ValueError
                if code and (len(code) < 3 or len(code) > 48 or
                             not all(char.isalnum() or char in '_-' for char in code)):
                    raise ValueError
                draft = {
                    'title': title, 'plan_tier': tier, 'feature': feature or None,
                    'max_uses': max_uses, 'ends_at': ends_at,
                    'target_telegram_ids': targets or None, 'code': code or None,
                }
            except Exception:
                self.db.rollback()
                await update.effective_message.reply_text(
                    "صيغة العرض غير صالحة. استخدم: title|plan_tier|feature|max_uses|end_ISO|telegram_ids_csv|coupon_code\n"
                    "اترك الحقول الاختيارية فارغة. لا توجد خصومات مالية في هذا النظام."
                )
                context.user_data['admin_waiting_for'] = state
                return ADMIN_MAIN
            context.user_data['pending_offer'] = draft
            context.user_data['pending_action'] = state
            await update.effective_message.reply_text(
                f"معاينة العرض: {draft['title']}\nالباقة: {draft['plan_tier'] or 'غير محددة'}\n"
                f"الميزة: {draft['feature'] or 'غير محددة'}\nالكوبون: {draft['code'] or 'لا يوجد'}\n"
                "هذا العرض لا يخصم أموالًا. هل تؤكد؟",
                reply_markup=get_confirmation_keyboard(),
            )
            return CONFIRM_ACTION
        if state == 'support_reply':
            ticket_id = context.user_data.get('selected_ticket_id')
            ticket = self.db.query(SupportTicket).filter_by(id=ticket_id).first()
            if not ticket or ticket.status != 'open':
                await update.effective_message.reply_text("التذكرة غير موجودة أو مغلقة.")
                return ADMIN_MAIN
            if not value or len(value) > 3000:
                await update.effective_message.reply_text("الرد فارغ أو أطول من الحد المسموح.")
                context.user_data['admin_waiting_for'] = 'support_reply'
                return SUPPORT_REPLY
            self.db.add(SupportMessage(
                ticket_id=ticket.id, sender_telegram_id=update.effective_user.id,
                sender_role='admin', message=value,
            ))
            if not self.record_audit(
                update.effective_user.id, 'support.reply', target_type='ticket',
                target_id=ticket.id, new_value={'message_recorded': True},
            ):
                await update.effective_message.reply_text(
                    "تعذر تسجيل الرد؛ لم يتم إرساله. تحقق من migration 015."
                )
                return ADMIN_MAIN
            try:
                await self.bot.send_message(chat_id=ticket.telegram_id, text=value, parse_mode=None)
                delivery = "تم حفظ الرد وإرساله للمستخدم."
            except Exception as exc:
                logger.warning("Support reply delivery failed (%s)", type(exc).__name__)
                delivery = "تم حفظ الرد لكن تعذر إرساله للمستخدم الآن."
            await update.effective_message.reply_text(delivery)
            return ADMIN_MAIN
        await update.effective_message.reply_text("لم أتعرف على خطوة الإدخال. أرسل /admin للعودة.")
        return ADMIN_MAIN
    
    async def handle_user_management(self, update: Update, context: CallbackContext) -> int:
        """Handle user management actions"""
        if not await self._require_admin(update):
            return ConversationHandler.END
        query = update.callback_query
        await query.answer()

        action = query.data.replace('user_', '')
        
        if action == 'back':
            return await self.dashboard(update, context)
        
        # Parse user selection
        if action.startswith('select_'):
            if not self.has_permission(update.effective_user.id, 'users.view'):
                await query.answer("❌ لا تملك صلاحية عرض المستخدمين.", show_alert=True)
                return USER_MANAGEMENT
            user_id = int(action.replace('select_', ''))
            context.user_data['selected_user'] = user_id
            return await self._show_user_details(update, context)
        elif action.startswith(('ban_', 'unban_', 'activate_', 'deactivate_', 'trial_',
                                'extend_subscription_', 'cancel_subscription_', 'message_')):
            if not self.has_permission(update.effective_user.id, 'users.manage'):
                await query.answer("❌ لا تملك صلاحية تعديل المستخدمين.", show_alert=True)
                return USER_MANAGEMENT
            action_name, user_id_text = action.rsplit('_', 1)
            if not user_id_text.isdigit():
                await query.answer("معرّف مستخدم غير صالح", show_alert=True)
                return USER_MANAGEMENT
            user_id = int(user_id_text)
            context.user_data['selected_user'] = user_id
            descriptions = {
                'ban': 'حظر المستخدم', 'unban': 'فك حظر المستخدم',
                'activate': 'تفعيل المستخدم', 'deactivate': 'تعطيل المستخدم',
                'trial': 'منح Trial مجاني لمدة 14 يومًا',
                'trial_extend': 'تمديد Trial لمدة 14 يومًا',
                'trial_revoke': 'إلغاء Trial الحالي',
                'extend_subscription': 'تمديد الاشتراك 30 يومًا',
                'cancel_subscription': 'إلغاء الاشتراك', 'message': 'إرسال رسالة للمستخدم',
            }
            if action_name == 'message':
                context.user_data['admin_waiting_for'] = 'user_message'
                await query.edit_message_text("اكتب نص الرسالة التي تريد إرسالها للمستخدم.")
                return USER_MANAGEMENT
            context.user_data['pending_action'] = action_name
            return await self._confirm_action(update, context, descriptions[action_name], action_name)
        
        elif action.startswith('make_admin_'):
            target_id = int(action.replace('make_admin_', ''))
            current_ids = ','.join(str(x) for x in self.admin_ids)
            await query.edit_message_text(
                f"⚠️ *ترقية المشرف تتطلب تعديل الإعدادات.*\n\n"
                f"أضف المستخدم `{target_id}` إلى `ADMIN_USER_IDS` في ملف `.env` "
                f"ثم أعد تشغيل البوت.\n\n"
                f"القيمة بعد التحديث:\n"
                f"`ADMIN_USER_IDS={current_ids},{target_id}`",
                parse_mode=ParseMode.MARKDOWN
            )
            return USER_MANAGEMENT
    
    async def _show_user_details(self, update: Update, context: CallbackContext) -> int:
        """Show detailed user information"""
        query = update.callback_query
        user_id = context.user_data['selected_user']
        
        user = self.user_repo.get_by_telegram_id(user_id)
        if not user:
            await query.edit_message_text("❌ لم يتم العثور على المستخدم.")
            return USER_MANAGEMENT
        
        # Use counters already persisted on User; querying full Trade entities
        # would fail against deployments awaiting migration 014.
        stats = {
            'summary': {
                'total_trades': user.total_trades or 0,
                'total_volume': user.total_volume or 0,
                'win_rate': user.win_rate,
                'net_profit': 'غير متاح',
            }
        }
        
        details = (
            f"*بيانات المستخدم: @{user.telegram_username or 'غير متاح'}*\n\n"
            f"المعرّف: `{user.telegram_id}`\n"
            f"الاسم: {user.full_name}\n"
            f"تاريخ التسجيل: {user.created_at.strftime('%Y-%m-%d')}\n\n"
            
            f"*حساب MT5:*\n"
            f"الحساب: `{user.mt5_account_id}`\n"
            f"الخادم: {user.mt5_server}\n"
            f"الحالة: {'✅ متصل' if user.mt_connected else '❌ غير متصل'}\n\n"
            
            f"*الاشتراك:*\n"
            f"الخطة: {user.subscription_tier}\n"
            f"ينتهي في: {user.subscription_expiry.strftime('%Y-%m-%d') if user.subscription_expiry else 'غير محدد'}\n"
            f"Trial: {'نشط حتى ' + user.trial_end.strftime('%Y-%m-%d') if user.trial_end and user.trial_end > datetime.utcnow() else ('منتهي' if user.trial_end else 'لا يوجد')}\n"
            f"آخر نشاط: {user.last_active.strftime('%Y-%m-%d %H:%M') if user.last_active else 'غير متاح'}\n"
            f"صفقات اليوم: {user.daily_trades}\n\n"
            
            f"*الإحصاءات (30 يومًا):*\n"
            f"الصفقات: {stats.get('summary', {}).get('total_trades', 0)}\n"
            f"الحجم: {stats.get('summary', {}).get('total_volume', 0):.2f}\n"
            f"نسبة الصفقات الرابحة: {stats.get('summary', {}).get('win_rate', 0):.1f}%\n"
            f"صافي الربح/الخسارة: غير متاح\n\n"
            
            f"الحالة: {'🟢 نشط' if user.is_active else '🔴 غير نشط'}\n"
            f"محظور: {'✅' if user.is_banned else '❌'}\n"
            f"الإحالة: {(user.subscription_features or {}).get('referral_attribution', 'غير متاح')}\n"
        )
        
        await safe_edit_message(
            query,
            details,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_admin_user_actions_keyboard(user)
        )
        
        return USER_MANAGEMENT
    
    async def _start_broadcast(self, update: Update, context: CallbackContext) -> int:
        """Start broadcast message flow"""
        query = update.callback_query
        targets = self.db.query(func.count(User.id)).filter(
            User.is_active.is_(True), User.is_verified.is_(True), User.is_banned.is_(False)
        ).scalar()
        
        await query.edit_message_text(
            "*📢 إرسال رسالة جماعية*\n\n"
            f"المستهدفون النشطون: {targets if targets is not None else 'غير متاح'}\n"
            "أرسل نص الرسالة لمعاينته قبل الإرسال.\n\n"
            "اكتب /cancel للإلغاء.",
            parse_mode=ParseMode.MARKDOWN
        )
        
        return BROADCAST
    
    async def handle_broadcast(self, update: Update, context: CallbackContext) -> int:
        """Handle broadcast message input"""
        if not await self._require_admin(update):
            return ConversationHandler.END
        message = update.message.text
        
        if message == '/cancel':
            await update.message.reply_text("❌ تم إلغاء الإرسال الجماعي.")
            return await self.dashboard(update, context)
        
        if not message or len(message) > 4000:
            await update.message.reply_text("الرسالة فارغة أو أطول من الحد المسموح.")
            return BROADCAST

        targets = self.db.query(func.count(User.id)).filter(
            User.is_active.is_(True), User.is_verified.is_(True), User.is_banned.is_(False)
        ).scalar()
        context.user_data['broadcast_message'] = message
        context.user_data['pending_action'] = 'broadcast'
        
        # Show preview and confirmation
        preview = (
            f"معاينة الرسالة الجماعية إلى {targets if targets is not None else 'غير متاح'} مستخدم:\n\n"
            f"{message}\n\nهل تؤكد الإرسال؟"
        )
        
        await update.message.reply_text(
            preview,
            reply_markup=get_confirmation_keyboard()
        )
        
        return CONFIRM_ACTION
    
    async def _show_system_stats(self, update: Update, context: CallbackContext) -> int:
        """Show detailed system statistics"""
        query = update.callback_query
        
        health = self.monitoring.get_system_health()
        system_info = health.get('system') or {}
        counts = self._get_admin_counts()
        connection_count = counts['connections_today']
        connection_rate = (
            counts['successful_connections'] / connection_count * 100
            if connection_count else 0
        )
        database_health = health.get('database') or {}
        
        stats_text = (
            "*📊 إحصاءات النظام*\n\n"
            f"*الأداء:*\n"
            f"المعالج: {self._metric_display(system_info, 'cpu')}\n"
            f"الذاكرة: {self._metric_display(system_info, 'memory')}\n"
            f"القرص: {self._metric_display(system_info, 'disk')}\n"
            f"استجابة قاعدة البيانات: {database_health.get('response_time_ms', 'غير متاح')} مللي ثانية\n\n"
            
            f"*المستخدمون:*\n"
            f"الإجمالي: {counts['users']}\n"
            f"النشطون: {counts['active_users']}\n"
            f"الموثقون: {counts['verified_users']}\n\n"
            
            f"*الاشتراكات:*\n"
            f"المجانية: {counts['subscriptions']['free']}\n"
            f"الأساسية: {counts['subscriptions']['basic']}\n"
            f"الاحترافية: {counts['subscriptions']['pro']}\n"
            f"المؤسسات: {counts['subscriptions']['enterprise']}\n\n"
            
            f"*الصفقات:*\n"
            f"آخر 24 ساعة: {counts['trades_today']}\n"
            f"الإجمالي: {counts['trades_total']}\n\n"
            
            f"*الاتصالات:*\n"
            f"معدل النجاح: {connection_rate:.2f}%\n"
            f"متوسط زمن الاستجابة: {counts['average_latency']:.2f} مللي ثانية\n"
        )
        
        await safe_edit_message(
            query,
            stats_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_admin_keyboard()
        )
        
        return ADMIN_MAIN
    
    async def _show_alerts(self, update: Update, context: CallbackContext) -> int:
        """Show system alerts"""
        query = update.callback_query
        
        try:
            alerts = self.monitoring.get_alerts()
        except Exception as exc:
            logger.warning("Could not read admin alerts (%s)", type(exc).__name__)
            alerts = None
        
        if alerts is None:
            alerts_text = "*⚠️ تعذر قراءة مؤشرات التنبيه في هذه البيئة.*"
        elif not alerts:
            alerts_text = "*✅ لا توجد تنبيهات نشطة*\n\nالنظام يعمل بصورة طبيعية."
        else:
            alerts_text = "*⚠️ تنبيهات نشطة*\n\n"
            for alert in alerts:
                level_icon = "🔴" if alert['level'] == 'critical' else "🟡"
                alerts_text += f"{level_icon} *{alert['metric']}*: {alert['message']}\n"
        
        await safe_edit_message(
            query,
            alerts_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_admin_keyboard()
        )
        
        return ADMIN_MAIN

    async def _show_admin_page(self, update: Update, title: str, body: str) -> int:
        query = update.callback_query
        if not await self._require_admin(update):
            return ConversationHandler.END
        if query:
            await safe_edit_message(query, f"*{title}*\n\n{body}",
                                    parse_mode=ParseMode.MARKDOWN,
                                    reply_markup=get_admin_section_keyboard())
        else:
            await update.effective_message.reply_text(
                f"*{title}*\n\n{body}", parse_mode=ParseMode.MARKDOWN,
                reply_markup=get_admin_section_keyboard())
        return ADMIN_MAIN

    async def _show_trials(self, update, context):
        now = datetime.utcnow()
        active = self.db.query(func.count(User.id)).filter(
            User.trial_start.isnot(None), User.trial_end > now
        ).scalar()
        expired = self.db.query(func.count(User.id)).filter(
            User.trial_start.isnot(None), User.trial_end <= now
        ).scalar()
        return await self._show_admin_page(
            update, "🎁 التجارب المجانية",
            f"تجارب نشطة: {active if active is not None else 'غير متاح'}\n"
            f"تجارب منتهية: {expired if expired is not None else 'غير متاح'}\n\n"
            "امنح Trial من ملف المستخدم بعد البحث عنه. لا تُنشأ أي معاملة مالية."
        )

    async def _show_subscriptions(self, update, context):
        now = datetime.utcnow()
        active = self.db.query(func.count(User.id)).filter(
            User.subscription_expiry > now
        ).scalar()
        expired = self.db.query(func.count(User.id)).filter(
            User.subscription_expiry.isnot(None), User.subscription_expiry <= now
        ).scalar()
        return await self._show_admin_page(
            update, "💳 الاشتراكات",
            f"نشطة: {active if active is not None else 'غير متاح'}\n"
            f"منتهية: {expired if expired is not None else 'غير متاح'}\n"
            "الإلغاء والتمديد متاحان من ملف المستخدم بعد البحث."
        )

    async def _show_plans(self, update, context):
        try:
            plans = self.db.query(SubscriptionPlan).all()
            plans.sort(key=lambda plan: (plan.display_order, plan.id))
            body = "\n".join(
                f"{plan.tier}: {plan.name} — {plan.price_monthly} {plan.currency}/شهر, "
                f"{plan.price_yearly} {plan.currency}/سنة — "
                f"{'نشطة' if plan.is_active else 'متوقفة'}, "
                f"{'ظاهرة' if plan.is_visible else 'مخفية'}, ترتيب {plan.display_order}"
                for plan in plans
            ) or "لا توجد باقات مسجلة."
            await safe_edit_message(
                update.callback_query, f"📦 الباقات والخطط\n\n{body}",
                parse_mode=None, reply_markup=get_admin_plans_keyboard(plans),
            )
            return ADMIN_MAIN
        except Exception as exc:
            self.db.rollback()
            logger.error("Admin plans lookup failed (%s)", type(exc).__name__)
            return await self._show_admin_page(
                update, "📦 الباقات والخطط",
                "تعذر تحميل الباقات؛ راجع سجل Admin الآمن وإعداد قاعدة البيانات."
            )

    async def _show_offers(self, update, context):
        try:
            offers = self.db.query(AdminOffer).order_by(AdminOffer.created_at.desc()).limit(20).all()
            body = "\n".join(
                f"#{offer.id} {offer.title} — {'نشط' if offer.is_active else 'متوقف'}"
                for offer in offers
            ) or "لا توجد عروض."
            rows = [[InlineKeyboardButton(
                f"{'⏸' if offer.is_active else '▶️'} #{offer.id} · {offer.title[:28]}",
                callback_data=f"admin_offer_toggle_{offer.id}",
            ), InlineKeyboardButton(
                "✏️ تعديل", callback_data=f"admin_offer_edit_{offer.id}"
            )] for offer in offers]
            rows.append([InlineKeyboardButton("➕ إنشاء عرض", callback_data='admin_offer_create')])
            rows.extend([
                [InlineKeyboardButton("🏠 الرئيسية", callback_data='admin_back')],
                [InlineKeyboardButton("⬅️ رجوع", callback_data='admin_back')],
                [InlineKeyboardButton("❌ إلغاء", callback_data='admin_cancel')],
            ])
        except Exception as exc:
            self.db.rollback()
            logger.error("Admin offers lookup failed (%s)", type(exc).__name__)
            body = "ميزة العروض تتطلب تطبيق migration 015 على قاعدة البيانات."
            rows = [[InlineKeyboardButton("🏠 الرئيسية", callback_data='admin_back')],
                    [InlineKeyboardButton("⬅️ رجوع", callback_data='admin_back')],
                    [InlineKeyboardButton("❌ إلغاء", callback_data='admin_cancel')]]
        await safe_edit_message(update.callback_query, f"🎯 العروض والكوبونات\n\n{body}",
                                parse_mode=None, reply_markup=InlineKeyboardMarkup(rows))
        return ADMIN_MAIN

    async def _show_support(self, update, context):
        try:
            tickets = self.db.query(SupportTicket).order_by(
                SupportTicket.created_at.desc()
            ).limit(20).all()
            body = "\n".join(
                f"#{ticket.id} [{ticket.status}] {ticket.subject} (user {ticket.telegram_id})"
                for ticket in tickets
            ) or "لا توجد تذاكر دعم."
            keyboard = [[InlineKeyboardButton(
                f"#{ticket.id} · {ticket.status}", callback_data=f"admin_ticket_{ticket.id}"
            )] for ticket in tickets]
            keyboard.extend([
                [InlineKeyboardButton("🏠 الرئيسية", callback_data='admin_back')],
                [InlineKeyboardButton("⬅️ رجوع", callback_data='admin_back')],
                [InlineKeyboardButton("❌ إلغاء", callback_data='admin_cancel')],
            ])
        except Exception as exc:
            self.db.rollback()
            logger.error("Admin support lookup failed (%s)", type(exc).__name__)
            body = "ميزة تذاكر الدعم تتطلب تطبيق migration 015 على قاعدة البيانات."
            keyboard = [
                [InlineKeyboardButton("🏠 الرئيسية", callback_data='admin_back')],
                [InlineKeyboardButton("⬅️ رجوع", callback_data='admin_back')],
                [InlineKeyboardButton("❌ إلغاء", callback_data='admin_cancel')],
            ]
        await safe_edit_message(update.callback_query, f"💬 الدعم\n\n{body}",
                                parse_mode=None,
                                reply_markup=InlineKeyboardMarkup(keyboard))
        return ADMIN_MAIN

    async def open_support_ticket(self, update: Update, context: CallbackContext):
        """Open a user support ticket without requiring an MT5 registration."""
        message = (update.effective_message.text or '')
        body = ' '.join(context.args or [])
        if message.startswith('/support') and not body:
            await update.effective_message.reply_text(
                "اكتب المشكلة بعد الأمر هكذا: /support وصف المشكلة. لا ترسل كلمات مرور أو مفاتيح سرية."
            )
            return
        if not body or len(body) > 3000:
            await update.effective_message.reply_text("رسالة الدعم فارغة أو أطول من الحد المسموح.")
            return
        telegram_id = update.effective_user.id
        try:
            user = self.user_repo.get_by_telegram_id(telegram_id)
            ticket = SupportTicket(
                user_id=user.id if user else None,
                telegram_id=telegram_id,
                subject=body[:160],
                status='open',
            )
            self.db.add(ticket)
            self.db.flush()
            self.db.add(SupportMessage(
                ticket_id=ticket.id, sender_telegram_id=telegram_id,
                sender_role='user', message=body,
            ))
            self.db.commit()
            await update.effective_message.reply_text(f"تم فتح تذكرة الدعم رقم #{ticket.id}.")
        except Exception as exc:
            self.db.rollback()
            logger.error("Support ticket creation failed (%s)", type(exc).__name__)
            await update.effective_message.reply_text("تعذر فتح تذكرة الدعم الآن. حاول لاحقًا.")

    async def _show_ticket(self, update, context, ticket_id):
        ticket = self.db.query(SupportTicket).filter_by(id=ticket_id).first()
        if not ticket:
            await update.callback_query.answer("التذكرة غير موجودة", show_alert=True)
            return ADMIN_MAIN
        messages = self.db.query(SupportMessage).filter_by(ticket_id=ticket.id).order_by(
            SupportMessage.created_at
        ).limit(30).all()
        body = "\n\n".join(
            f"{item.sender_role} ({item.created_at:%Y-%m-%d %H:%M}): {item.message[:700]}"
            for item in messages
        ) or "لا توجد رسائل."
        buttons = [[InlineKeyboardButton("↩️ رد", callback_data=f"admin_ticket_reply_{ticket.id}")]]
        action = 'close' if ticket.status == 'open' else 'reopen'
        buttons.append([InlineKeyboardButton(
            "🔒 إغلاق" if action == 'close' else "🔓 إعادة فتح",
            callback_data=f"admin_ticket_{action}_{ticket.id}",
        )])
        buttons.extend([
            [InlineKeyboardButton("🏠 الرئيسية", callback_data='admin_back')],
            [InlineKeyboardButton("⬅️ رجوع", callback_data='admin_support')],
            [InlineKeyboardButton("❌ إلغاء", callback_data='admin_cancel')],
        ])
        await safe_edit_message(
            update.callback_query,
            f"تذكرة #{ticket.id} — {ticket.status}\nالمستخدم: {ticket.telegram_id}\n\n{body}",
            parse_mode=None,
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        context.user_data['selected_ticket_id'] = ticket.id
        return ADMIN_MAIN

    async def _show_notifications(self, update, context):
        try:
            count = self.db.query(func.count(Notification.id)).scalar()
            body = f"الإشعارات المسجلة: {count if count is not None else 'غير متاح'}"
        except Exception as exc:
            self.db.rollback()
            logger.error("Admin notifications lookup failed (%s)", type(exc).__name__)
            body = "بيانات الإشعارات غير متاحة."
        return await self._show_admin_page(update, "🔔 الإشعارات", body)

    async def _show_status(self, update, context):
        health = self.monitoring.get_system_health()
        db_status = (health.get('database') or {}).get('status', 'غير متاح')
        mode = 'dry-run' if settings.TRADING_DRY_RUN else 'live'
        body = (
            f"البوت: {'يعمل' if self.bot else 'غير متاح'}\n"
            f"قاعدة البيانات: {db_status}\n"
            f"Telegram: {'متصل' if self.bot else 'غير متاح'}\n"
            "Worker: غير متاح\nScheduler: غير متاح\n"
            f"وضع التداول: {mode}\n"
            f"TRADING_DRY_RUN: {str(settings.TRADING_DRY_RUN).lower()}\n"
            f"مدة التشغيل: {health.get('uptime', 'غير متاح')} ثانية\n"
        )
        return await self._show_admin_page(update, "🤖 حالة البوت", body)

    async def _show_settings(self, update, context):
        return await self._show_admin_page(
            update, "⚙️ إعدادات البوت",
            f"TRADING_DRY_RUN={str(settings.TRADING_DRY_RUN).lower()}\n"
            "الإعدادات السرية لا تُعرض ولا تُعدّل من Telegram."
        )

    async def _show_emergency(self, update, context):
        try:
            state = self.db.query(AdminSetting).filter_by(key='emergency_stop').first()
            value = state.value if state else 'false'
            body = f"حالة إيقاف التنفيذ: {'مفعّل' if value == 'true' else 'متوقف'}"
        except Exception as exc:
            self.db.rollback()
            logger.error("Admin emergency state lookup failed (%s)", type(exc).__name__)
            body = "حالة الطوارئ غير متاحة حتى تطبيق migration 015. لا يُفترض أن الإيقاف مفعّل."
        query = update.callback_query
        if query:
            await safe_edit_message(query, f"*🛑 الطوارئ*\n\n{body}",
                                    parse_mode=ParseMode.MARKDOWN,
                                    reply_markup=get_admin_emergency_keyboard())
        else:
            await update.effective_message.reply_text(
                f"*🛑 الطوارئ*\n\n{body}", parse_mode=ParseMode.MARKDOWN,
                reply_markup=get_admin_emergency_keyboard())
        return ADMIN_MAIN

    async def _show_roles(self, update, context):
        try:
            rows = self.db.query(AdminRole).order_by(AdminRole.telegram_id).all()
            body = "\n".join(f"{row.telegram_id}: {row.role}" for row in rows)
            buttons = [[InlineKeyboardButton(
                f"❌ إزالة {row.telegram_id} ({row.role})",
                callback_data=f"admin_role_remove_{row.telegram_id}",
            )] for row in rows]
            buttons.append([InlineKeyboardButton("➕ إضافة دور", callback_data='admin_role_add')])
        except Exception as exc:
            self.db.rollback()
            logger.error("Admin roles lookup failed (%s)", type(exc).__name__)
            body = "الأدوار الإضافية تتطلب تطبيق migration 015. الأدمن المضبوط في البيئة يبقى SUPER_ADMIN."
            buttons = []
        buttons.extend([
            [InlineKeyboardButton("🏠 الرئيسية", callback_data='admin_back')],
            [InlineKeyboardButton("⬅️ رجوع", callback_data='admin_back')],
            [InlineKeyboardButton("❌ إلغاء", callback_data='admin_cancel')],
        ])
        await safe_edit_message(update.callback_query,
                                f"🔐 الأدمن والصلاحيات\n\n{body or 'لا توجد أدوار إضافية.'}",
                                parse_mode=None, reply_markup=InlineKeyboardMarkup(buttons))
        return ADMIN_MAIN

    async def _show_audit(self, update, context):
        try:
            rows = self.db.query(AdminAuditLog).order_by(
                AdminAuditLog.created_at.desc()
            ).limit(20).all()
            body = "\n".join(
                f"{row.created_at:%Y-%m-%d %H:%M} — {row.admin_telegram_id}: {row.action} ({row.result})"
                for row in rows
            ) or "لا توجد أحداث مسجلة."
        except Exception as exc:
            self.db.rollback()
            logger.error("Admin audit lookup failed (%s)", type(exc).__name__)
            body = "سجل الإدارة يتطلب تطبيق migration 015 على قاعدة البيانات."
        return await self._show_admin_page(update, "📝 سجل الإدارة", body)
    
    async def _confirm_action(self, update: Update, context: CallbackContext,
                              action_desc: str, action_code: str = None) -> int:
        """Show confirmation dialog"""
        query = update.callback_query
        
        context.user_data['pending_action'] = action_code or action_desc
        
        await query.edit_message_text(
            f"هل أنت متأكد من رغبتك في {action_desc}؟",
            reply_markup=get_confirmation_keyboard()
        )
        
        return CONFIRM_ACTION
    
    async def confirm_action(self, update: Update, context: CallbackContext) -> int:
        """Handle action confirmation"""
        if not await self._require_admin(update):
            return ConversationHandler.END
        query = update.callback_query
        await query.answer()
        if query.data not in {'confirm_yes', 'confirm_no'}:
            await query.answer("تأكيد غير صالح", show_alert=True)
            return CONFIRM_ACTION
        action = context.user_data.get('pending_action')
        if query.data == 'confirm_no':
            context.user_data.pop('pending_action', None)
            context.user_data.pop('pending_message', None)
            context.user_data.pop('selected_user', None)
            await query.edit_message_text("تم إلغاء الإجراء.")
            return await self.dashboard(update, context)

        admin_id = update.effective_user.id
        if action in {'role_add', 'role_remove'}:
            if not self.has_permission(admin_id, 'admin.manage'):
                await query.edit_message_text("❌ يتطلب هذا الإجراء SUPER_ADMIN.")
                return ADMIN_MAIN
            try:
                if action == 'role_add':
                    data = context.user_data.get('pending_role') or {}
                    target_id, role_name = data.get('telegram_id'), data.get('role')
                    if not target_id or role_name not in ROLE_PERMISSIONS or role_name == 'SUPER_ADMIN':
                        await query.edit_message_text("بيانات الدور غير صالحة.")
                        return ADMIN_MAIN
                    existing = self.db.query(AdminRole).filter_by(telegram_id=target_id).first()
                    if existing:
                        if existing.is_active:
                            await query.edit_message_text("هذا المستخدم لديه دور نشط بالفعل.")
                            return ADMIN_MAIN
                        old_value = {'role': existing.role, 'is_active': existing.is_active}
                        existing.role = role_name
                        existing.permissions = []
                        existing.is_active = True
                        existing.created_by = admin_id
                    else:
                        existing = AdminRole(telegram_id=target_id, role=role_name,
                                             permissions=[], is_active=True, created_by=admin_id)
                        self.db.add(existing)
                        self.db.flush()
                        old_value = None
                    target_id = existing.telegram_id
                    new_value = {'role': existing.role, 'is_active': existing.is_active}
                else:
                    target_id = context.user_data.get('selected_role_id')
                    existing = self.db.query(AdminRole).filter_by(
                        telegram_id=target_id, is_active=True
                    ).first()
                    if not existing:
                        await query.edit_message_text("الدور غير موجود أو معطّل.")
                        return ADMIN_MAIN
                    old_value = {'role': existing.role, 'is_active': existing.is_active}
                    existing.is_active = False
                    new_value = {'role': existing.role, 'is_active': False}
                if not self.record_audit(
                    admin_id, f'role.{action}', target_type='admin', target_id=target_id,
                    old_value=old_value, new_value=new_value,
                ):
                    await query.edit_message_text("تعذر تسجيل العملية؛ لم يتغير الدور.")
                    return ADMIN_MAIN
            except Exception as exc:
                self.db.rollback()
                logger.error("Admin role update failed (%s)", type(exc).__name__)
                await query.edit_message_text("تعذر تحديث الدور. تحقق من migration 015.")
                return ADMIN_MAIN
            context.user_data.pop('pending_role', None)
            context.user_data.pop('selected_role_id', None)
            context.user_data.pop('pending_action', None)
            await self._show_roles(update, context)
            return ADMIN_MAIN

        if action in {'emergency_stop', 'emergency_resume'}:
            if not self.has_permission(admin_id, 'emergency_stop'):
                await query.edit_message_text("❌ لا تملك صلاحية التحكم بالطوارئ.")
                return ADMIN_MAIN
            try:
                state = self.db.query(AdminSetting).filter_by(key='emergency_stop').first()
                old = state.value if state else 'false'
                new = 'true' if action == 'emergency_stop' else 'false'
                if state is None:
                    state = AdminSetting(key='emergency_stop', value=new,
                                         updated_by=admin_id)
                    self.db.add(state)
                else:
                    state.value = new
                    state.updated_by = admin_id
                if not self.record_audit(
                    admin_id, action, target_type='system', target_id='emergency_stop',
                    old_value={'value': old}, new_value={'value': new},
                ):
                    await query.edit_message_text(
                        "تعذر تسجيل الإجراء؛ لم يتغير وضع الطوارئ.",
                        reply_markup=get_admin_emergency_keyboard(),
                    )
                    return ADMIN_MAIN
            except Exception as exc:
                self.db.rollback()
                logger.error("Admin emergency update failed (%s)", type(exc).__name__)
                await query.edit_message_text(
                    "تعذر تحديث وضع الطوارئ. تحقق من تطبيق migration 015.",
                    reply_markup=get_admin_emergency_keyboard(),
                )
                return ADMIN_MAIN
            context.user_data.pop('pending_action', None)
            await query.edit_message_text(
                "تم إيقاف التنفيذ الجديد." if new == 'true' else "تم رفع إيقاف التنفيذ الجديد.",
                reply_markup=get_admin_emergency_keyboard(),
            )
            return ADMIN_MAIN

        if action in {'plan_create', 'plan_edit', 'plan_toggle'}:
            if not self.has_permission(admin_id, 'plans.manage'):
                await query.edit_message_text("❌ لا تملك صلاحية إدارة الباقات.")
                return ADMIN_MAIN
            try:
                if action == 'plan_toggle':
                    plan = self.db.query(SubscriptionPlan).filter_by(
                        id=context.user_data.get('selected_plan_id')
                    ).first()
                    if not plan:
                        await query.edit_message_text("الباقة غير موجودة.")
                        return ADMIN_MAIN
                    new_active = bool(context.user_data.get('plan_toggle_value'))
                    if plan.tier == 'free' and not new_active:
                        await query.edit_message_text("لا يمكن تعطيل باقة free الأساسية.")
                        return ADMIN_MAIN
                    old_value = {'is_active': plan.is_active}
                    plan.is_active = new_active
                    new_value = {'is_active': plan.is_active}
                else:
                    draft = context.user_data.get('pending_plan') or {}
                    if action == 'plan_create':
                        plan = SubscriptionPlan(**draft, features={
                            '_admin': {'is_active': True,
                                       'is_visible': draft.get('is_visible', True),
                                       'display_order': draft.get('display_order', 0)}
                        })
                        self.db.add(plan)
                        self.db.flush()
                        old_value = None
                    else:
                        plan = self.db.query(SubscriptionPlan).filter_by(
                            id=context.user_data.get('selected_plan_id')
                        ).first()
                        if not plan:
                            await query.edit_message_text("الباقة غير موجودة.")
                            return ADMIN_MAIN
                        old_value = {
                            'name': plan.name, 'price_monthly': str(plan.price_monthly),
                            'price_yearly': str(plan.price_yearly),
                            'max_trades_per_day': plan.max_trades_per_day,
                            'max_position_size': plan.max_position_size,
                            'max_symbols': plan.max_symbols,
                            'is_visible': plan.is_visible,
                            'display_order': plan.display_order,
                        }
                        for key, value in draft.items():
                            setattr(plan, key, value)
                    new_value = {
                        'name': plan.name, 'tier': plan.tier,
                        'price_monthly': str(plan.price_monthly),
                        'price_yearly': str(plan.price_yearly),
                        'max_trades_per_day': plan.max_trades_per_day,
                        'max_position_size': plan.max_position_size,
                        'max_symbols': plan.max_symbols,
                        'is_visible': plan.is_visible,
                        'display_order': plan.display_order,
                    }
                if not self.record_audit(
                    admin_id, f'plan.{action}', target_type='plan', target_id=plan.id,
                    old_value=old_value, new_value=new_value,
                ):
                    await query.edit_message_text("تعذر تسجيل التغيير؛ لم تتغير الباقة.")
                    return ADMIN_MAIN
            except Exception as exc:
                self.db.rollback()
                logger.error("Admin plan update failed (%s)", type(exc).__name__)
                await query.edit_message_text("تعذر حفظ الباقة. تحقق من migration 015 والبيانات.")
                return ADMIN_MAIN
            context.user_data.pop('pending_plan', None)
            context.user_data.pop('pending_action', None)
            context.user_data.pop('selected_plan_id', None)
            await self._show_plans(update, context)
            return ADMIN_MAIN

        if action in {'offer_create', 'offer_edit', 'offer_toggle'}:
            if not self.has_permission(admin_id, 'offers.manage'):
                await query.edit_message_text("❌ لا تملك صلاحية إدارة العروض.")
                return ADMIN_MAIN
            try:
                if action == 'offer_toggle':
                    offer = self.db.query(AdminOffer).filter_by(
                        id=context.user_data.get('selected_offer_id')
                    ).first()
                    if not offer:
                        await query.edit_message_text("العرض غير موجود.")
                        return ADMIN_MAIN
                    old_value = {'is_active': offer.is_active}
                    offer.is_active = bool(context.user_data.get('offer_toggle_value'))
                    new_value = {'is_active': offer.is_active}
                else:
                    draft = context.user_data.get('pending_offer') or {}
                    if action == 'offer_create':
                        offer = AdminOffer(**draft, starts_at=datetime.utcnow(),
                                           is_active=False, created_by=admin_id)
                        self.db.add(offer)
                        self.db.flush()
                        old_value = None
                    else:
                        offer = self.db.query(AdminOffer).filter_by(
                            id=context.user_data.get('selected_offer_id')
                        ).first()
                        if not offer:
                            await query.edit_message_text("العرض غير موجود.")
                            return ADMIN_MAIN
                        old_value = {'title': offer.title, 'plan_tier': offer.plan_tier,
                                     'feature': offer.feature, 'code': offer.code,
                                     'is_active': offer.is_active}
                        for key, value in draft.items():
                            setattr(offer, key, value)
                    new_value = {'title': offer.title, 'plan_tier': offer.plan_tier,
                                 'feature': offer.feature, 'code': offer.code,
                                 'is_active': offer.is_active}
                if not self.record_audit(
                    admin_id, f'offer.{action}', target_type='offer', target_id=offer.id,
                    old_value=old_value, new_value=new_value,
                ):
                    await query.edit_message_text("تعذر تسجيل العملية؛ لم يتم تغيير العرض.")
                    return ADMIN_MAIN
            except Exception as exc:
                self.db.rollback()
                logger.error("Admin offer update failed (%s)", type(exc).__name__)
                await query.edit_message_text("تعذر تحديث العرض. تحقق من migration 015 والحقول.")
                return ADMIN_MAIN
            context.user_data.pop('pending_action', None)
            context.user_data.pop('pending_offer', None)
            context.user_data.pop('selected_offer_id', None)
            await self._show_offers(update, context)
            return ADMIN_MAIN

        if action == 'broadcast':
            if not self.has_permission(admin_id, 'broadcast.send'):
                await query.edit_message_text("❌ لا تملك صلاحية الإرسال الجماعي.")
                return ConversationHandler.END
            if not self.record_audit(admin_id, 'broadcast.start', target_type='users',
                                     result='requested'):
                await query.edit_message_text("تعذر تسجيل العملية؛ لم يتم إرسال الرسالة.")
                return ADMIN_MAIN
            result = await self._execute_broadcast(context.user_data.get('broadcast_message', ''))
            success = bool(result and result.get('failed', 0) == 0)
            self.record_audit(admin_id, 'broadcast.complete', target_type='users',
                              new_value={'total': result.get('total', 0),
                                         'success': result.get('success', 0),
                                         'failed': result.get('failed', 0)},
                              result='success' if success else 'partial')
            context.user_data.pop('pending_action', None)
            context.user_data.pop('broadcast_message', None)
            await query.edit_message_text(
                f"اكتمل الإرسال. المستهدفون: {result.get('total', 0)}، "
                f"نجح: {result.get('success', 0)}، فشل: {result.get('failed', 0)}.",
                reply_markup=get_admin_keyboard(),
            )
            return ADMIN_MAIN

        user_id = context.user_data.get('selected_user')
        user = self.user_repo.get_by_telegram_id(user_id) if user_id else None
        if not user:
            await query.edit_message_text("لم يتم العثور على المستخدم المستهدف.")
            return USER_MANAGEMENT
        if not self.has_permission(admin_id, 'users.manage'):
            await query.edit_message_text("❌ لا تملك صلاحية تعديل المستخدمين.")
            return USER_MANAGEMENT

        old_value = {'is_active': user.is_active, 'is_banned': user.is_banned,
                     'subscription_tier': user.subscription_tier,
                     'subscription_expiry': user.subscription_expiry.isoformat() if user.subscription_expiry else None,
                     'trial_start': user.trial_start.isoformat() if user.trial_start else None,
                     'trial_end': user.trial_end.isoformat() if user.trial_end else None}
        now = datetime.utcnow()
        features = dict(user.subscription_features or {})
        if action == 'ban':
            user.is_banned = True
        elif action == 'unban':
            user.is_banned = False
        elif action == 'activate':
            user.is_active = True
        elif action == 'deactivate':
            user.is_active = False
        elif action == 'trial':
            if user.trial_used:
                await query.edit_message_text("سبق استخدام Trial لهذا المستخدم؛ لم يتم إنشاء Trial مكرر.")
                return USER_MANAGEMENT
            pro_plan = self.db.query(SubscriptionPlan).filter_by(tier='pro').first()
            if not pro_plan:
                await query.edit_message_text("لا توجد باقة pro مرتبطة بالـTrial؛ لم يتغير الحساب.")
                return USER_MANAGEMENT
            user.trial_used = True
            user.trial_start = now
            user.trial_end = now + timedelta(days=14)
            preserved = {key: features[key] for key in ('referral_attribution',) if key in features}
            features = {
                'max_trades': pro_plan.max_trades_per_day,
                'max_position_size': float(pro_plan.max_position_size),
                'max_symbols': pro_plan.max_symbols,
                'multiple_tps': pro_plan.supports_multiple_tps,
                'auto_trading': pro_plan.supports_auto_trading,
                'api_access': pro_plan.supports_api,
                'max_connections': pro_plan.max_connections,
                'rate_limit': pro_plan.rate_limit_per_second,
                'support_priority': pro_plan.support_priority,
                **preserved,
                'admin_trial': {
                    'plan_tier': 'pro', 'previous_tier': user.subscription_tier,
                    'previous_expiry': user.subscription_expiry.isoformat() if user.subscription_expiry else None,
                    'previous_features': {key: value for key, value in features.items()
                                          if key in {'max_trades', 'max_position_size', 'max_symbols',
                                                     'multiple_tps', 'auto_trading', 'api_access',
                                                     'max_connections', 'rate_limit', 'support_priority'}},
                },
            }
            user.subscription_features = features
            user.subscription_tier = 'pro'
            user.subscription_expiry = user.trial_end
        elif action == 'trial_extend':
            if not user.trial_end or not features.get('admin_trial'):
                await query.edit_message_text("لا يوجد Trial إداري قابل للتمديد.")
                return USER_MANAGEMENT
            user.trial_end = max(user.trial_end, now) + timedelta(days=14)
            user.subscription_expiry = user.trial_end
        elif action == 'trial_revoke':
            marker = features.pop('admin_trial', None)
            if not marker:
                await query.edit_message_text("لا يوجد Trial إداري قابل للإلغاء.")
                return USER_MANAGEMENT
            user.subscription_tier = marker.get('previous_tier', 'free')
            previous_expiry = marker.get('previous_expiry')
            user.subscription_expiry = datetime.fromisoformat(previous_expiry) if previous_expiry else None
            user.trial_end = now
            features = dict(marker.get('previous_features') or {})
            referral = (user.subscription_features or {}).get('referral_attribution')
            if referral:
                features['referral_attribution'] = referral
            user.subscription_features = features
        elif action == 'extend_subscription':
            user.subscription_expiry = max(user.subscription_expiry or now, now) + timedelta(days=30)
        elif action == 'cancel_subscription':
            user.subscription_tier = 'free'
            user.subscription_expiry = now
        elif action == 'user_message':
            if not self.record_audit(admin_id, 'user.message.requested', target_type='user',
                                     target_id=user.telegram_id, result='requested'):
                await query.edit_message_text("تعذر تسجيل العملية؛ لم يتم إرسال الرسالة.")
                return USER_MANAGEMENT
            try:
                await self.bot.send_message(
                    chat_id=user.telegram_id,
                    text=context.user_data.get('pending_message', ''),
                    parse_mode=None,
                )
                result = 'success'
            except Exception as exc:
                logger.warning("Admin user message failed (%s)", type(exc).__name__)
                result = 'failed'
            self.record_audit(admin_id, 'user.message.complete', target_type='user',
                              target_id=user.telegram_id, result=result,
                              failure_reason='telegram_delivery_failed' if result == 'failed' else None)
            context.user_data.pop('pending_message', None)
            context.user_data.pop('pending_action', None)
            await query.edit_message_text(
                "تم إرسال الرسالة." if result == 'success' else "تعذر إرسال الرسالة لهذا المستخدم.",
                reply_markup=get_admin_keyboard(),
            )
            return ADMIN_MAIN
        else:
            await query.edit_message_text("الإجراء غير معروف؛ لم يتم تغيير البيانات.")
            return ADMIN_MAIN

        new_value = {'is_active': user.is_active, 'is_banned': user.is_banned,
                     'subscription_tier': user.subscription_tier,
                     'subscription_expiry': user.subscription_expiry.isoformat() if user.subscription_expiry else None,
                     'trial_start': user.trial_start.isoformat() if user.trial_start else None,
                     'trial_end': user.trial_end.isoformat() if user.trial_end else None}
        if not self.record_audit(admin_id, f'user.{action}', target_type='user',
                                 target_id=user.telegram_id, old_value=old_value,
                                 new_value=new_value):
            await query.edit_message_text("تعذر تسجيل العملية؛ تم التراجع عن التغيير.")
            return USER_MANAGEMENT
        context.user_data.pop('pending_action', None)
        context.user_data.pop('selected_user', None)
        await self.dashboard(update, context)
        try:
            await self.bot.send_message(
                chat_id=user.telegram_id,
                text=f"تم تحديث حالة حسابك بواسطة فريق الإدارة. الإجراء: {action}.",
            )
        except Exception as exc:
            logger.info("Could not notify user after admin change (%s)", type(exc).__name__)
        return ADMIN_MAIN
    
    async def _execute_broadcast(self, message: str):
        """Execute broadcast to all users"""
        result = await self.notification.broadcast(message)
        
        # Notify admins
        for admin_id in self.admin_ids:
            await self.bot.send_message(
                chat_id=admin_id,
                text=f"📢 اكتمل الإرسال الجماعي: تم التسليم إلى {result['success']} مستخدمًا، وتعذر الإرسال إلى {result['failed']}"
            )
        return result
    
    async def stats(self, update: Update, context: CallbackContext):
        """Quick stats command"""
        if not await self._require_admin(update):
            return
        health = self.monitoring.get_system_health()
        system_info = health.get('system') or {}
        counts = self._get_admin_counts()
        
        quick_stats = (
            f"*إحصاءات النظام*\n"
            f"مدة التشغيل: {health.get('uptime', 0)/3600:.1f} ساعة\n"
            f"المعالج: {self._metric_display(system_info, 'cpu')}\n"
            f"الذاكرة: {self._metric_display(system_info, 'memory')}\n"
            f"المستخدمون: {counts['users']}\n"
            f"الصفقات خلال 24 ساعة: {counts['trades_today']}"
        )
        
        await update.message.reply_text(quick_stats, parse_mode=ParseMode.MARKDOWN)
    
    async def broadcast(self, update: Update, context: CallbackContext):
        """Quick broadcast command"""
        if not await self._require_admin(update):
            return
        # Check if message provided
        if not context.args:
            await update.message.reply_text("طريقة الاستخدام: /broadcast <message>")
            return
        
        message = ' '.join(context.args)
        
        # Start broadcast
        asyncio.create_task(self._execute_broadcast(message))
        await update.message.reply_text("📢 بدأ الإرسال الجماعي.")
    

    async def handle_callback(self, update: Update, context: CallbackContext) -> None:
        """Route admin callbacks after checking authorization on every invocation."""
        if not await self._require_admin(update):
            return
        query = update.callback_query
        data = query.data or ""
        if data.startswith("admin:"):
            action = data.split(":", 1)[1]
        elif data.startswith("admin_"):
            action = data.removeprefix("admin_")
        elif data.startswith("user_"):
            action = data
        else:
            await query.answer("إجراء إدارة غير معروف", show_alert=True)
            return

        logger.debug("Admin callback received: %s", action)
        try:
            permission = {
                "plans": "plans.view", "trials": "trial.grant",
                "subscriptions": "subscriptions.view", "offers": "offers.view",
                "support": "support.view", "broadcast": "broadcast.send",
                "stats": "statistics.view", "alerts": "statistics.view",
                "notifications": "settings.view", "status": "settings.view",
                "settings": "settings.view", "emergency": "emergency_stop",
                "emergency_stop": "emergency_stop", "emergency_resume": "emergency_stop",
                "roles": "admin.manage", "audit": "admin.manage",
                "users": "users.view",
            }.get(action, "users.view")
            if action.startswith('ticket_reply_'):
                permission = 'support.reply'
            elif action.startswith(('ticket_', 'ticket_close_', 'ticket_reopen_')):
                permission = 'support.view'
            elif action.startswith('offer_'):
                permission = 'offers.manage'
            elif action.startswith('plan_'):
                permission = 'plans.manage'
            if not self.has_permission(update.effective_user.id, permission):
                await query.answer("❌ لا تملك صلاحية هذا الإجراء.", show_alert=True)
                return
            if action == "users":
                await query.answer()
                await self._show_user_management(update, context)
            elif action == "search":
                await query.answer()
                context.user_data['admin_waiting_for'] = 'user_search'
                await query.edit_message_text(
                    "أرسل Telegram ID الرقمي أو username (مع @ أو بدونه) للبحث.",
                    reply_markup=get_admin_section_keyboard(),
                )
            elif action == "broadcast":
                await query.answer()
                await self._start_broadcast(update, context)
            elif action == "stats":
                await query.answer()
                await self._show_system_stats(update, context)
            elif action == "alerts":
                await query.answer()
                await self._show_alerts(update, context)
            elif action == "plans":
                await query.answer()
                await self._show_plans(update, context)
            elif action == 'plan_create' or action.startswith('plan_edit_'):
                if action.startswith('plan_edit_'):
                    plan_id = action.rsplit('_', 1)[1]
                    if not plan_id.isdigit():
                        await query.answer("رقم باقة غير صالح", show_alert=True)
                        return
                    context.user_data['selected_plan_id'] = int(plan_id)
                    context.user_data['admin_waiting_for'] = 'plan_edit'
                else:
                    context.user_data['admin_waiting_for'] = 'plan_create'
                await query.answer()
                await query.edit_message_text(
                    "أرسل الحقول مفصولة بـ | بهذا الترتيب:\n"
                    "name|tier|price_monthly|price_yearly|max_trades_per_day|max_position_size|max_symbols|visible,order"
                )
            elif action.startswith('plan_toggle_'):
                plan_id = action.rsplit('_', 1)[1]
                if not plan_id.isdigit():
                    await query.answer("رقم باقة غير صالح", show_alert=True)
                    return
                plan = self.db.query(SubscriptionPlan).filter_by(id=int(plan_id)).first()
                if not plan:
                    await query.answer("الباقة غير موجودة", show_alert=True)
                    return
                context.user_data['selected_plan_id'] = plan.id
                context.user_data['plan_toggle_value'] = not plan.is_active
                context.user_data['pending_action'] = 'plan_toggle'
                await query.answer()
                await query.edit_message_text(
                    "تغيير تفعيل الباقة لن يبدل ميزات الاشتراكات الحالية المحفوظة للمستخدمين. هل تؤكد؟",
                    reply_markup=get_confirmation_keyboard(),
                )
            elif action == "trials":
                await query.answer()
                await self._show_trials(update, context)
            elif action == "subscriptions":
                await query.answer()
                await self._show_subscriptions(update, context)
            elif action == "offers":
                await query.answer()
                await self._show_offers(update, context)
            elif action == 'offer_create' or action.startswith('offer_edit_'):
                if action.startswith('offer_edit_'):
                    offer_id = action.rsplit('_', 1)[1]
                    if not offer_id.isdigit() or not self.db.query(AdminOffer.id).filter_by(id=int(offer_id)).first():
                        await query.answer("العرض غير موجود", show_alert=True)
                        return
                    context.user_data['selected_offer_id'] = int(offer_id)
                    context.user_data['admin_waiting_for'] = 'offer_edit'
                else:
                    context.user_data['admin_waiting_for'] = 'offer_create'
                await query.answer()
                await query.edit_message_text(
                    "أرسل الحقول مفصولة بـ | بهذا الترتيب:\n"
                    "title|plan_tier|feature|max_uses|end_ISO|telegram_ids_csv|coupon_code\n"
                    "اترك الاختياري فارغًا. لا تدخل سعرًا أو خصمًا؛ لا يوجد تنفيذ مالي للعروض."
                )
            elif action.startswith('offer_toggle_'):
                offer_id = action.rsplit('_', 1)[1]
                if not offer_id.isdigit():
                    await query.answer("رقم عرض غير صالح", show_alert=True)
                    return
                offer = self.db.query(AdminOffer).filter_by(id=int(offer_id)).first()
                if not offer:
                    await query.answer("العرض غير موجود", show_alert=True)
                    return
                context.user_data['selected_offer_id'] = offer.id
                context.user_data['pending_action'] = 'offer_toggle'
                context.user_data['offer_toggle_value'] = not offer.is_active
                await query.answer()
                await query.edit_message_text(
                    "هل تؤكد تغيير حالة هذا العرض؟",
                    reply_markup=get_confirmation_keyboard(),
                )
            elif action == "support":
                await query.answer()
                await self._show_support(update, context)
            elif action.startswith('ticket_reply_'):
                ticket_id = action.rsplit('_', 1)[1]
                if not ticket_id.isdigit():
                    await query.answer("رقم تذكرة غير صالح", show_alert=True)
                    return
                context.user_data['selected_ticket_id'] = int(ticket_id)
                context.user_data['admin_waiting_for'] = 'support_reply'
                await query.answer()
                await query.edit_message_text(f"اكتب ردك على التذكرة #{ticket_id}.")
            elif action.startswith('ticket_close_') or action.startswith('ticket_reopen_'):
                if not self.has_permission(update.effective_user.id, 'support.reply'):
                    await query.answer("❌ لا تملك صلاحية تغيير حالة التذكرة.", show_alert=True)
                    return
                ticket_id = action.rsplit('_', 1)[1]
                if not ticket_id.isdigit():
                    await query.answer("رقم تذكرة غير صالح", show_alert=True)
                    return
                ticket = self.db.query(SupportTicket).filter_by(id=int(ticket_id)).first()
                if not ticket:
                    await query.answer("التذكرة غير موجودة", show_alert=True)
                    return
                old = ticket.status
                ticket.status = 'closed' if action.startswith('ticket_close_') else 'open'
                ticket.closed_at = datetime.utcnow() if ticket.status == 'closed' else None
                if not self.record_audit(
                    update.effective_user.id, f'support.{ticket.status}',
                    target_type='ticket', target_id=ticket.id,
                    old_value={'status': old}, new_value={'status': ticket.status},
                ):
                    await query.answer("تعذر تسجيل التغيير", show_alert=True)
                    return
                await query.answer()
                await self._show_ticket(update, context, ticket.id)
            elif action.startswith('ticket_'):
                ticket_id = action.removeprefix('ticket_')
                if not ticket_id.isdigit():
                    await query.answer("رقم تذكرة غير صالح", show_alert=True)
                    return
                await query.answer()
                await self._show_ticket(update, context, int(ticket_id))
            elif action == "notifications":
                await query.answer()
                await self._show_notifications(update, context)
            elif action == "status":
                await query.answer()
                await self._show_status(update, context)
            elif action == "settings":
                await query.answer()
                await self._show_settings(update, context)
            elif action == "emergency":
                await query.answer()
                await self._show_emergency(update, context)
            elif action in {"emergency_stop", "emergency_resume"}:
                context.user_data['pending_action'] = action
                description = "إيقاف تنفيذ الإشارات الجديدة" if action == "emergency_stop" else "استئناف التنفيذ بعد التحقق"
                await query.answer()
                await query.edit_message_text(
                    f"هل تؤكد {description}؟ وضع dry-run سيبقى كما هو.",
                    reply_markup=get_confirmation_keyboard(),
                )
            elif action == "roles":
                await query.answer()
                await self._show_roles(update, context)
            elif action == 'role_add':
                await query.answer()
                context.user_data['admin_waiting_for'] = 'role_assignment'
                await query.edit_message_text(
                    "أرسل Telegram ID ثم الدور بهذا الشكل: 123456789|SUPPORT\n"
                    "الأدوار المتاحة: ADMIN, SUPPORT, MODERATOR, ANALYST."
                )
            elif action.startswith('role_remove_'):
                target_text = action.removeprefix('role_remove_')
                if not target_text.isdigit():
                    await query.answer("معرّف الأدمن غير صالح", show_alert=True)
                    return
                target_id = int(target_text)
                if target_id in self.admin_ids:
                    await query.answer("لا يمكن إزالة Super Admin المضبوط في البيئة.", show_alert=True)
                    return
                context.user_data['selected_role_id'] = target_id
                context.user_data['pending_action'] = 'role_remove'
                await query.answer()
                await query.edit_message_text(
                    f"هل تؤكد إزالة الدور عن Telegram ID {target_id}؟",
                    reply_markup=get_confirmation_keyboard(),
                )
            elif action == "audit":
                await query.answer()
                await self._show_audit(update, context)
            elif action in {"back", "home"}:
                await query.answer()
                await self.dashboard(update, context)
            elif action == "cancel":
                await query.answer()
                context.user_data.clear()
                await self.dashboard(update, context)
            elif action == "close":
                await query.answer()
                await query.edit_message_text("👑 انتهت جلسة المشرف.")
                context.user_data.clear()
            elif action.startswith("user_"):
                await self.handle_user_management(update, context)
            else:
                await query.answer("إجراء إدارة غير معروف", show_alert=True)
        except Exception as exc:
            logger.error("Admin callback failed (%s)", type(exc).__name__)
            try:
                await query.answer("تعذر تنفيذ الإجراء. حاول مجددًا.", show_alert=True)
                await query.edit_message_text("تعذر تنفيذ الإجراء. حاول مجددًا.")
            except Exception:
                pass
    	
    def get_states(self):
        """Return conversation states using bound instance methods"""
        # Defined after class so AdminHandler is in scope
        return  {
            ADMIN_MAIN: [CallbackQueryHandler(self.handle_callback, pattern='^(admin_|admin:|user_)'),
                         MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_admin_text)],
            USER_MANAGEMENT: [CallbackQueryHandler(self.handle_callback, pattern='^(admin_|admin:|user_)'),
                              MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_admin_text)],
            BROADCAST: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_broadcast)],
            SYSTEM_STATS: [CallbackQueryHandler(self.handle_callback, pattern='^(admin_|admin:|user_)')],
            CONFIRM_ACTION: [CallbackQueryHandler(self.confirm_action, pattern='^confirm_')],
        }
