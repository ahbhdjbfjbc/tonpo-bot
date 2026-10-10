# fx/bot/registration.py
import logging
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.constants import ParseMode
from telegram.ext import ConversationHandler, CallbackContext, MessageHandler, filters, CallbackQueryHandler
from sqlalchemy.orm import Session

from database.repositories import UserRepository
from services.auth import AuthService
#from services.mt5_manager import MT5ConnectionManager
# MT5ConnectionManager removed — gateway handles MT5 connections now
from services.notification import NotificationService
from core.validators import CredentialsValidator
#from gateway_client import ExecutionProvider, GatewayConfig
from config.settings import settings

logger = logging.getLogger(__name__)

# Conversation states
(ENTER_ACCOUNT, ENTER_PASSWORD, ENTER_SERVER, 
 CONFIRM_CREDENTIALS, VERIFYING, COMPLETE) = range(6)

class RegistrationHandler:
    def __init__(self, db_session: Session, bot, mt5_manager=None):
        self.db = db_session
        self.bot = bot
        self.user_repo = UserRepository(db_session)
        self.auth_service = AuthService(db_session)
        self._pending_passwords = {}
        
        # Initialize execution provider
        self.execution_provider = None  # injected by main.py after startup
    
    async def initialize(self):
        """Initialize the execution provider"""
        from config.settings import settings
        await self.execution_provider.initialize(settings.gateway_config)
    
    async def start(self, update: Update, context: CallbackContext) -> int:
        """Start the registration process"""
        user = update.effective_user
        if str(getattr(settings, "ENGINE_PROVIDER", "tonpo")).lower() == "metadocker":
            await update.message.reply_text(
                "ربط MetaDocker لا يستخدم نموذج كلمة مرور MT5 القديم. "
                "افتح لوحة الويب واربط EngineInstance من صفحة MT5، ثم عد إلى البوت للتحقق من الاتصال."
            )
            return ConversationHandler.END
        if not hasattr(self, '_pending_passwords'):
            self._pending_passwords = {}
        self._pending_passwords.pop(user.id, None)

        # Clear interrupted form data without dropping a /start referral.
        pending_referrer_id = context.user_data.get('pending_referrer_telegram_id')
        context.user_data.clear()
        context.user_data.pop('mt5_password', None)
        if pending_referrer_id is not None:
            context.user_data['pending_referrer_telegram_id'] = pending_referrer_id

        # Check if already registered
        existing = self.user_repo.get_by_telegram_id(user.id)
        if existing:
            if existing.is_verified:
                await update.message.reply_text(
                    "✅ أنت مسجل بالفعل! استخدم /settings لتحديث بيانات الدخول."
                )
                return ConversationHandler.END
            else:
                # Continue with existing unverified user
                context.user_data['user_id'] = existing.id
        
        welcome_text = (
            "🚀 *لنبدأ إعداد حسابك!*\n\n"
            "نحتاج إلى بيانات MetaTrader 5 لربط حسابك.\n\n"
            "⚠️ *تنبيه مهم:*\n"
            "• لن تُحفظ كلمة مرور MT5 في قاعدة بيانات البوت\n"
            "• ننصح بالبدء بحساب تجريبي\n"
            "• يمكنك تغيير البيانات لاحقًا من /settings\n\n"
            "أدخل **معرّف حساب MT5** (رقم الدخول):"
        )
        
        await update.message.reply_text(welcome_text, parse_mode=ParseMode.MARKDOWN)
        return ENTER_ACCOUNT
    
    async def receive_account(self, update: Update, context: CallbackContext) -> int:
        """Receive and validate account ID"""
        account_id = update.message.text.strip()
        
        # Validate format using CredentialsValidator
        is_valid, error = CredentialsValidator.validate_account_id(account_id)
        if not is_valid:
            await update.message.reply_text(f"❌ {error}\nيرجى المحاولة مجددًا:")
            return ENTER_ACCOUNT
        
        context.user_data['mt5_account'] = account_id
        await update.message.reply_text(
            "✅ تم استلام معرّف الحساب.\n\n"
            "أدخل الآن **كلمة مرور MT5**:\n"
            "_(لن تُحفظ في قاعدة بيانات البوت)_",
            parse_mode=ParseMode.MARKDOWN
        )
        return ENTER_PASSWORD
    
    async def receive_password(self, update: Update, context: CallbackContext) -> int:
        """Receive and temporarily store password"""
        password = update.message.text
        
        # Basic validation
        is_valid, error = CredentialsValidator.validate_password(password)
        if not is_valid:
            await update.message.reply_text(f"❌ {error}\nيرجى المحاولة مجددًا:")
            return ENTER_PASSWORD
        
        self._pending_passwords[update.effective_user.id] = password
        context.user_data.pop('mt5_password', None)
        await update.message.reply_text(
            "✅ تم استلام كلمة المرور.\n\n"
            "أدخل أخيرًا **اسم خادم MT5**:\n"
            "_(مثل IC Markets-Demo أو ICMarkets-Server)_"
        )
        return ENTER_SERVER
    
    async def receive_server(self, update: Update, context: CallbackContext) -> int:
        """Receive server and show confirmation"""
        server = update.message.text.strip()
        
        # Validate server format using CredentialsValidator
        is_valid, error = CredentialsValidator.validate_server(server)
        if not is_valid:
            await update.message.reply_text(f"❌ {error}\nيرجى المحاولة مجددًا:")
            return ENTER_SERVER
        
        context.user_data['mt5_server'] = server
        
        # The password stays in handler memory and is never put in persistent user_data.
        if update.effective_user.id not in self._pending_passwords:
            await update.message.reply_text('انتهت صلاحية كلمة المرور. أعد إدخالها من /register.')
            return ENTER_PASSWORD

        from bot.keyboards import get_confirmation_keyboard

        confirm_text = (
            "*يرجى تأكيد بيانات الدخول:*\n\n"
            f"معرّف الحساب: `{context.user_data['mt5_account']}`\n"
            f"الخادم: {server}\n"
            "كلمة المرور: ••••••••\n\n"
            "هل هذه البيانات صحيحة؟"
        )
        
        await update.message.reply_text(
            confirm_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_confirmation_keyboard()
        )
        return CONFIRM_CREDENTIALS
    
    async def confirm_credentials(self, update: Update, context: CallbackContext) -> int:
        """Handle confirmation callback"""
        query = update.callback_query
        await query.answer()
        
        if query.data == 'confirm_yes':
            await query.edit_message_text(
                "🔄 *جارٍ التحقق من بيانات الدخول...*\n"
                "قد يستغرق ذلك 30 ثانية.",
                parse_mode=ParseMode.MARKDOWN
            )
            
            # Start verification
            return await self._verify_credentials(update, context)
        else:
            self._pending_passwords.pop(update.effective_user.id, None)
            context.user_data.pop('mt5_password', None)
            await query.edit_message_text(
                "❌ تم إلغاء التسجيل. استخدم /register للبدء من جديد."
            )
            return ConversationHandler.END
    
    async def _verify_credentials(self, update: Update, context: CallbackContext) -> int:
        """Send credentials to CMG, store only what comes back"""
        user_id = update.effective_user.id
        query = update.callback_query
        
        # Pull the password from non-persistent handler memory and consume it once.
        password = self._pending_passwords.pop(user_id, None)
        context.user_data.pop('mt5_password', None)
        if not password:
            await query.edit_message_text('انتهت صلاحية كلمة المرور. أعد التسجيل من /register.')
            context.user_data.clear()
            return ConversationHandler.END
        account = context.user_data.pop('mt5_account')
        server = context.user_data.pop('mt5_server')
        
        try:
                if not self.execution_provider:
                        raise RuntimeError("Gateway not available — please try again later")
                        
                # Forward to CMG — bot never touches these again after this call
                success, message, creds = await self.execution_provider.register_user(
                    telegram_id=user_id,
                    mt5_account=account,
                    mt5_password=password,
                    mt5_server=server,
                )
                # The password is no longer needed after the provider call.
                # Account/server identifiers are non-secret routing metadata
                # needed to persist the connection record below.
                del password
                
                if not success:
                        raise RuntimeError(message)
                
                # Bot only stores the routing keys
                from services.auth import encrypt_gateway_api_key
                gateway_api_key    = encrypt_gateway_api_key(creds['gateway_api_key'])
                gateway_account_id = creds['gateway_account_id']
                
                existing = self.user_repo.get_by_telegram_id(user_id)
                if existing:
                        self.user_repo.update_user(
                            user_id,
                            is_verified=True,
                            mt_connected=True,
                            mt5_account_id=account,
                            mt5_server=server,
                            gateway_user_id=creds['gateway_user_id'],
                            gateway_api_key=gateway_api_key,
                            gateway_account_id=gateway_account_id,
                        )
                else:
                        from bot.referrals import add_referral_attribution
                        features = add_referral_attribution(
                            None,
                            context.user_data.get('pending_referrer_telegram_id'),
                            user_id,
                        )
                        create_kwargs = {
                            'telegram_username': update.effective_user.username,
                            'first_name': update.effective_user.first_name,
                            'last_name': update.effective_user.last_name,
                            'is_verified': True,
                            'mt_connected': True,
                            'mt5_account_id': account,
                            'mt5_server': server,
                            'gateway_user_id': creds['gateway_user_id'],
                            'gateway_api_key': gateway_api_key,
                            'gateway_account_id': gateway_account_id,
                        }
                        if features:
                            create_kwargs['subscription_features'] = features
                        self.user_repo.create_user(
                            telegram_id=user_id,
                            **create_kwargs,
                        )
                        
                context.user_data.pop('pending_referrer_telegram_id', None)
                # Show success + risk selection
                from bot.keyboards import get_risk_keyboard
                await query.edit_message_text(
                    "✅ *تم ربط الحساب بنجاح!*\n\n"
                    "الحالة: 🟢 نشط\n\n"
                    "اضبط الآن نسبة المخاطرة الافتراضية لكل صفقة:",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=get_risk_keyboard()
                )
                return COMPLETE
        
        except Exception:
                # Provider exceptions may echo credential payloads; never include them in logs or chat.
                logger.error(f"Registration failed for user {user_id}; provider error redacted")
                
                # Clean up any partial DB state
                try:
                        self.user_repo.update_user(
                            user_id,
                            gateway_user_id=None,
                            gateway_api_key=None,
                            gateway_account_id=None,
                            is_verified=False,
                            mt_connected=False,
                        )
                except Exception:
                        pass
                
                # Strip raw HTML from gateway/nginx errors
                user_msg = "تعذر الاتصال بالبوابة. يرجى المحاولة لاحقًا."
                await query.edit_message_text(
                    f"❌ *خطأ في التسجيل*\n\n{user_msg}\n\n"
                    "تحقق من بيانات الدخول ثم حاول مجددًا باستخدام /register.",
                    parse_mode=ParseMode.MARKDOWN
                )
                context.user_data.clear()
                return ConversationHandler.END
                        
    async def complete(self, update: Update, context: CallbackContext) -> int:
        """Complete registration with risk preference"""
        query = update.callback_query
        await query.answer()
        
        if query.data.startswith('risk_'):
            # Parse risk percentage
            risk_str = query.data.replace('risk_', '')
            if risk_str == 'custom':
                await query.edit_message_text(
                    "أدخل نسبة المخاطرة المخصصة (مثل 1.5 لتعيين 1.5%):"
                )
                return COMPLETE
            else:
                risk = float(risk_str) / 100
        else:
            # Custom risk input
            try:
                risk = float(update.message.text) / 100
                if risk < 0.001 or risk > 0.1:
                    raise ValueError
            except:
                await update.message.reply_text(
                    "❌ نسبة مخاطرة غير صالحة. أدخل رقمًا بين 0.1 و10:"
                )
                return COMPLETE
        
        # Save risk preference
        user_id = update.effective_user.id
        self.user_repo.update_user(user_id, default_risk_factor=risk)
        
        # Clear sensitive data
        self._pending_passwords.pop(update.effective_user.id, None)
        context.user_data.pop('mt5_password', None)
        context.user_data.clear()
        
        # Send completion message
        completion_text = (
            "🎉 *اكتمل التسجيل!* 🎉\n\n"
            f"تم ضبط المخاطرة الافتراضية على *{risk*100:.1f}%*\n\n"
            "*الخطوات التالية:*\n"
            "• استخدم /trade لإنشاء أول صفقة\n"
            "• استخدم /settings لتخصيص التفضيلات\n"
            "• استخدم /help لعرض الأوامر\n\n"
            "نتمنى لك تداولًا موفقًا! 📈"
        )
        
        if hasattr(update, 'callback_query'):
            await query.edit_message_text(completion_text, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text(completion_text, parse_mode=ParseMode.MARKDOWN)
        
        return ConversationHandler.END
    
    async def cancel(self, update: Update, context: CallbackContext) -> int:
        """Cancel registration"""
        await update.message.reply_text(
            "❌ تم إلغاء التسجيل. استخدم /register للبدء من جديد."
        )
        
        # Clear any stored data
        self._pending_passwords.pop(update.effective_user.id, None)
        context.user_data.pop('mt5_password', None)
        context.user_data.clear()
        
        return ConversationHandler.END

    def get_states(self):
        """Return conversation states using bound instance methods"""
        # Defined after class so RegistrationHandler is in scope
        return  {
            ENTER_ACCOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.receive_account)],
            ENTER_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.receive_password)],
            ENTER_SERVER: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.receive_server)],
            CONFIRM_CREDENTIALS: [CallbackQueryHandler(self.confirm_credentials, pattern='^confirm_')],
            VERIFYING: [],  # No input while verifying
            COMPLETE: [
                CallbackQueryHandler(self.complete, pattern='^risk_'),
                MessageHandler(filters.TEXT & ~filters.COMMAND, self.complete),
            ],
        }
