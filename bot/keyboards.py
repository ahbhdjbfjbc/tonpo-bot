# fx/bot/keyboards.py
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from typing import List, Dict, Any, Optional
from config.settings import settings


def get_mini_app_keyboard() -> Optional[InlineKeyboardMarkup]:
    """Return the configured Telegram Web App launcher, if provisioned."""
    url = getattr(settings, 'WEB_APP_URL', None)
    if not url:
        return None
    return InlineKeyboardMarkup([[
        InlineKeyboardButton('📱 فتح Tonpo', web_app=WebAppInfo(url=url))
    ]])


def get_confirmation_keyboard(action: Optional[str] = None) -> InlineKeyboardMarkup:
    """Get yes/no confirmation keyboard"""
    if action == 'close_all_positions':
        yes_callback = 'position_close_all:yes'
        no_callback = 'position_close_all:no'
    else:
        yes_callback = 'confirm_yes'
        no_callback = 'confirm_no'
    keyboard = [
        [
            InlineKeyboardButton("✅ نعم", callback_data=yes_callback),
            InlineKeyboardButton("❌ لا", callback_data=no_callback)
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_close_all_positions_keyboard() -> InlineKeyboardMarkup:
    """Offer the existing close-all feature only when positions are present."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "إغلاق جميع الصفقات",
            callback_data='position_close_all',
        )
    ]])


def get_risk_keyboard() -> InlineKeyboardMarkup:
    """Get risk selection keyboard"""
    keyboard = [
        [
            InlineKeyboardButton("0.5% (متحفظ)", callback_data='risk_0.5'),
            InlineKeyboardButton("1% (معتدل)", callback_data='risk_1.0')
        ],
        [
            InlineKeyboardButton("2% (مرتفع)", callback_data='risk_2.0'),
            InlineKeyboardButton("مخصص", callback_data='risk_custom')
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_plans_keyboard() -> InlineKeyboardMarkup:
    """Get subscription plans keyboard"""
    keyboard = [
        [
            InlineKeyboardButton("مجانية", callback_data='plan_free'),
            InlineKeyboardButton("أساسية $9.99", callback_data='plan_basic')
        ],
        [
            InlineKeyboardButton("احترافية $29.99", callback_data='plan_pro'),
            InlineKeyboardButton("مؤسسات $99.99", callback_data='plan_enterprise')
        ],
        [InlineKeyboardButton("مقارنة الخطط", callback_data='plan_compare')]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_upgrade_keyboard(plan_tier: str) -> InlineKeyboardMarkup:
    """Get upgrade confirmation keyboard for a specific plan"""
    keyboard = [
        [
            InlineKeyboardButton(
                "💰 الدفع عبر USDT (ERC-20)",
                callback_data=f'pay_usdt_{plan_tier}'
            )
        ],
        [
            InlineKeyboardButton(
                "₿ الدفع عبر BTC",
                callback_data=f'pay_btc_{plan_tier}'
            )
        ],
        [
            InlineKeyboardButton("📅 شهري", callback_data=f'period_monthly_{plan_tier}'),
            InlineKeyboardButton("📅 سنوي (وفر 17%)", callback_data=f'period_yearly_{plan_tier}')
        ],
        [
            InlineKeyboardButton("🔙 العودة إلى الخطط", callback_data='plan_compare')
        ]
    ]
    return InlineKeyboardMarkup(keyboard)
  
def get_payment_pending_keyboard(payment_id: str) -> InlineKeyboardMarkup:
    """Get keyboard shown while waiting for payment"""
    keyboard = [
        [
            InlineKeyboardButton("🔄 التحقق من الحالة", callback_data=f'pay_check_{payment_id}')
        ],
        [
            InlineKeyboardButton("❌ إلغاء الدفع", callback_data=f'pay_cancel_{payment_id}')
        ]
    ]
    return InlineKeyboardMarkup(keyboard)      
def get_trade_confirmation_keyboard(trade_data: Dict[str, Any]) -> InlineKeyboardMarkup:
    """Get trade confirmation keyboard"""
    keyboard = [
        [
            InlineKeyboardButton("✅ تنفيذ", callback_data='trade_execute'),
            InlineKeyboardButton("📊 تعديل المخاطر", callback_data='trade_adjust')
        ],
        [
            InlineKeyboardButton("✏️ تعديل", callback_data='trade_modify'),
            InlineKeyboardButton("❌ إلغاء", callback_data='trade_cancel')
        ]
    ]
    
    # Add multiple TPs info if applicable
    if len(trade_data.get('signal', {}).get('take_profits', [])) > 1:
        keyboard.insert(0, [
            InlineKeyboardButton("🎯 عدة مستويات جني أرباح", callback_data='trade_info')
        ])
    
    return InlineKeyboardMarkup(keyboard)


def get_execution_keyboard() -> InlineKeyboardMarkup:
    """Get execution decision keyboard"""
    keyboard = [
        [
            InlineKeyboardButton("✅ تنفيذ الآن", callback_data='trade_execute'),
            InlineKeyboardButton("❌ إلغاء", callback_data='trade_cancel')
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_settings_keyboard() -> InlineKeyboardMarkup:
    """Get main settings keyboard"""
    keyboard = [
        [
            InlineKeyboardButton("⚖️ المخاطر", callback_data='settings_risk'),
            InlineKeyboardButton("🔔 الإشعارات", callback_data='settings_notifications')
        ],
        [
            InlineKeyboardButton("📊 الرموز", callback_data='settings_symbols'),
            InlineKeyboardButton("🔌 الاتصال", callback_data='settings_connection')
        ],
        [
            InlineKeyboardButton("🔑 API", callback_data='settings_api'),
            InlineKeyboardButton("❌ إغلاق", callback_data='settings_close')
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_risk_settings_keyboard(user) -> InlineKeyboardMarkup:
    """Get risk settings keyboard"""
    keyboard = [
        [
            InlineKeyboardButton(
                f"المخاطر الافتراضية ({user.default_risk_factor*100:.1f}%)",
                callback_data='risk_default'
            )
        ],
        [
            InlineKeyboardButton(
                f"الحجم الأقصى ({user.max_position_size})",
                callback_data='risk_max_size'
            )
        ],
        [InlineKeyboardButton("🔙 رجوع", callback_data='risk_back')]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_notification_settings_keyboard(settings) -> InlineKeyboardMarkup:
    """Get notification settings keyboard"""
    keyboard = [
        [
            InlineKeyboardButton(
                f"الصفقات: {'✅' if settings.notify_on_trade else '❌'}",
                callback_data='notify_trade'
            )
        ],
        [
            InlineKeyboardButton(
                f"الأخطاء: {'✅' if settings.notify_on_error else '❌'}",
                callback_data='notify_error'
            )
        ],
        [
            InlineKeyboardButton(
                f"التقرير اليومي: {'✅' if settings.notify_daily_report else '❌'}",
                callback_data='notify_daily'
            )
        ],
        [
            InlineKeyboardButton(
                f"موعد التقرير ({settings.notification_hour}:00)",
                callback_data='notify_hour'
            )
        ],
        [InlineKeyboardButton("🔙 رجوع", callback_data='notify_back')]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_symbol_settings_keyboard(user) -> InlineKeyboardMarkup:
    """Get symbol settings keyboard"""
    keyboard = [
        [InlineKeyboardButton("➕ السماح برمز", callback_data='symbol_add')],
        [InlineKeyboardButton("➖ حظر رمز", callback_data='symbol_remove')],
        [InlineKeyboardButton("🔄 مسح الكل", callback_data='symbol_clear')],
        [InlineKeyboardButton("🔙 رجوع", callback_data='symbol_back')]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_connection_settings_keyboard() -> InlineKeyboardMarkup:
    """Get connection settings keyboard"""
    keyboard = [
        [InlineKeyboardButton("🔄 اختبار الاتصال", callback_data='conn_test')],
        [InlineKeyboardButton("✏️ تحديث بيانات الدخول", callback_data='conn_update')],
        [InlineKeyboardButton("🔙 رجوع", callback_data='conn_back')]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_api_settings_keyboard(settings) -> InlineKeyboardMarkup:
    """Get API settings keyboard"""
    keyboard = []
    
    if settings.api_enabled and settings.api_key:
        keyboard.append([InlineKeyboardButton("🔄 إنشاء مفتاح جديد", callback_data='api_generate')])
        keyboard.append([InlineKeyboardButton("❌ إلغاء المفتاح", callback_data='api_revoke')])
    else:
        keyboard.append([InlineKeyboardButton("🔑 إنشاء مفتاح API", callback_data='api_generate')])
    
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data='api_back')])
    
    return InlineKeyboardMarkup(keyboard)


def get_admin_keyboard() -> InlineKeyboardMarkup:
    """Get admin main keyboard"""
    keyboard = [
        [InlineKeyboardButton("👥 المستخدمون", callback_data='admin_users'),
         InlineKeyboardButton("📦 الباقات", callback_data='admin_plans')],
        [InlineKeyboardButton("🎁 التجارب", callback_data='admin_trials'),
         InlineKeyboardButton("💳 الاشتراكات", callback_data='admin_subscriptions')],
        [InlineKeyboardButton("🎯 العروض", callback_data='admin_offers'),
         InlineKeyboardButton("💬 الدعم", callback_data='admin_support')],
        [InlineKeyboardButton("📢 الرسائل الجماعية", callback_data='admin_broadcast'),
         InlineKeyboardButton("🔔 الإشعارات", callback_data='admin_notifications')],
        [InlineKeyboardButton("📊 الإحصاءات", callback_data='admin_stats'),
         InlineKeyboardButton("🤖 حالة البوت", callback_data='admin_status')],
        [InlineKeyboardButton("⚠️ التنبيهات", callback_data='admin_alerts'),
         InlineKeyboardButton("⚙️ الإعدادات الآمنة", callback_data='admin_settings')],
        [InlineKeyboardButton("🛑 الطوارئ", callback_data='admin_emergency'),
         InlineKeyboardButton("🔐 الصلاحيات", callback_data='admin_roles')],
        [InlineKeyboardButton("📝 سجل الإدارة", callback_data='admin_audit')],
        [InlineKeyboardButton("❌ إغلاق", callback_data='admin_close')]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_admin_section_keyboard() -> InlineKeyboardMarkup:
    """Consistent navigation footer for admin sections."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 الرئيسية", callback_data='admin_back')],
        [InlineKeyboardButton("⬅️ رجوع", callback_data='admin_back')],
        [InlineKeyboardButton("❌ إلغاء", callback_data='admin_cancel')],
    ])


def get_admin_emergency_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛑 Emergency Stop", callback_data='admin_emergency_stop')],
        [InlineKeyboardButton("▶️ Resume", callback_data='admin_emergency_resume')],
        [InlineKeyboardButton("🏠 الرئيسية", callback_data='admin_back')],
        [InlineKeyboardButton("⬅️ رجوع", callback_data='admin_back')],
        [InlineKeyboardButton("❌ إلغاء", callback_data='admin_cancel')],
    ])


def get_admin_plans_keyboard(plans) -> InlineKeyboardMarkup:
    rows = []
    for plan in plans:
        rows.append([
            InlineKeyboardButton(
                f"{'⏸' if plan.is_active else '▶️'} {plan.tier}",
                callback_data=f"admin_plan_toggle_{plan.id}",
            ),
            InlineKeyboardButton("✏️ تعديل", callback_data=f"admin_plan_edit_{plan.id}"),
        ])
    rows.append([InlineKeyboardButton("➕ إنشاء باقة", callback_data='admin_plan_create')])
    rows.extend([
        [InlineKeyboardButton("🏠 الرئيسية", callback_data='admin_back')],
        [InlineKeyboardButton("⬅️ رجوع", callback_data='admin_back')],
        [InlineKeyboardButton("❌ إلغاء", callback_data='admin_cancel')],
    ])
    return InlineKeyboardMarkup(rows)


def get_admin_user_keyboard(users: List) -> InlineKeyboardMarkup:
    """Get admin user selection keyboard"""
    keyboard = []
    
    for user in users[:5]:  # Show first 5
        username = user.telegram_username or str(user.telegram_id)
        keyboard.append([
            InlineKeyboardButton(
                f"@{username} - {user.subscription_tier}",
                callback_data=f'user_select_{user.telegram_id}'
            )
        ])

    keyboard.append([InlineKeyboardButton("🔎 بحث عن مستخدم", callback_data='admin_search')])
    
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data='user_back')])
    
    return InlineKeyboardMarkup(keyboard)


def get_admin_user_actions_keyboard(user) -> InlineKeyboardMarkup:
    """Get admin user actions keyboard"""
    keyboard = []
    
    if user.is_banned:
        keyboard.append([InlineKeyboardButton("🔓 إلغاء حظر المستخدم", callback_data=f'user_unban_{user.telegram_id}')])
    else:
        keyboard.append([InlineKeyboardButton("🔒 حظر المستخدم", callback_data=f'user_ban_{user.telegram_id}')])

    if user.is_active:
        keyboard.append([InlineKeyboardButton("⏸ تعطيل المستخدم", callback_data=f'user_deactivate_{user.telegram_id}')])
    else:
        keyboard.append([InlineKeyboardButton("▶️ تفعيل المستخدم", callback_data=f'user_activate_{user.telegram_id}')])
    keyboard.append([InlineKeyboardButton("🎁 Trial للمستخدم", callback_data=f'user_trial_{user.telegram_id}')])
    keyboard.append([InlineKeyboardButton("↗️ تمديد Trial", callback_data=f'user_trial_extend_{user.telegram_id}')])
    keyboard.append([InlineKeyboardButton("⛔ إلغاء Trial", callback_data=f'user_trial_revoke_{user.telegram_id}')])
    keyboard.append([InlineKeyboardButton("⏳ تمديد الاشتراك", callback_data=f'user_extend_subscription_{user.telegram_id}')])
    keyboard.append([InlineKeyboardButton("✖️ إلغاء الاشتراك", callback_data=f'user_cancel_subscription_{user.telegram_id}')])
    keyboard.append([InlineKeyboardButton("💬 مراسلة المستخدم", callback_data=f'user_message_{user.telegram_id}')])
    
    # Add admin promotion if not already admin
    if user.telegram_id not in settings.ADMIN_USER_IDS:
        keyboard.append([InlineKeyboardButton("👑 تعيين مشرف", callback_data=f'user_make_admin_{user.telegram_id}')])
    
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data='user_back')])
    
    return InlineKeyboardMarkup(keyboard)


def get_pagination_keyboard(page: int, total_pages: int, prefix: str) -> InlineKeyboardMarkup:
    """Get pagination keyboard"""
    keyboard = []
    row = []
    
    if page > 1:
        row.append(InlineKeyboardButton("◀️ السابق", callback_data=f'{prefix}_page_{page-1}'))
    
    row.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data='noop'))
    
    if page < total_pages:
        row.append(InlineKeyboardButton("التالي ▶️", callback_data=f'{prefix}_page_{page+1}'))
    
    keyboard.append(row)
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=f'{prefix}_back')])
    
    return InlineKeyboardMarkup(keyboard)


def get_help_keyboard(section: str = 'main') -> InlineKeyboardMarkup:
    """Build navigation buttons for the help sections used by callbacks."""
    sections = [
        ('التداول', 'trading'),
        ('التسجيل', 'registration'),
        ('المخاطر', 'risk'),
        ('الاشتراكات', 'subscription'),
        ('API', 'api'),
    ]
    keyboard = [[InlineKeyboardButton(label, callback_data=f'help_{key}')]
                for label, key in sections if key != section]
    if section != 'main':
        keyboard.append([InlineKeyboardButton('المساعدة الرئيسية', callback_data='help_main')])
    return InlineKeyboardMarkup(keyboard)
