# fx/bot/trading.py
import asyncio
import logging
import telegram
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ConversationHandler, CallbackContext, MessageHandler, CallbackQueryHandler, filters
from sqlalchemy.orm import Session

from database.repositories import UserRepository
from services.trade_executor import TradeExecutor
from services.risk_service import RiskService
from services.subscription import SubscriptionService
from services.signal_pipeline import SignalPipeline
from core.models import UnifiedSignal
from bot.keyboards import get_trade_confirmation_keyboard
from bot.message_utils import safe_edit_message
from utils.formatters import format_trade_calculation, format_positions, format_balance

logger = logging.getLogger(__name__)

# Conversation states
(ENTER_TRADE, CONFIRM_TRADE, ADJUST_RISK, EXECUTING) = range(4)

class TradingHandler:
    """
    Handles trading conversations
    """
    
    def __init__(self, db_session, bot, mt5_manager=None, execution_provider=None):
        self.db = db_session
        self.bot = bot
        self.execution_provider = execution_provider
        self.trade_executor = TradeExecutor(db_session, bot, execution_provider=execution_provider)
        self.user_repo = UserRepository(db_session)
        self.risk_service = RiskService()
        self.sub_service = SubscriptionService(db_session)
        
        # Track active trades for rate limiting
        self.active_trades = {}
        self.mt5_manager_ready = asyncio.Event()
        if execution_provider is not None:
        	self.mt5_manager_ready.set()
        	
    async def wait_for_mt5_manager(self, timeout: float = 30.0) -> bool:
    	"""Wait for mt5_manager to be initialized"""
    	try:
    		await asyncio.wait_for(self.mt5_manager_ready.wait(), timeout=timeout)
    		return True
    	except asyncio.TimeoutError:
    		return False
    	
    async def start_trade(self, update: Update, context: CallbackContext) -> int:
        """Start the trade placement flow"""
        user_id = update.effective_user.id
        
        # Check if user is registered
        user = self.user_repo.get_by_telegram_id(user_id)
        if not user or not user.is_verified:
            await update.message.reply_text(
                "❌ يجب التسجيل أولًا!\n\nاستخدم /register لربط حساب MT5."
            )
            return ConversationHandler.END
        
        # Check if already in a trade
        if user_id in self.active_trades:
            await update.message.reply_text(
                "⚠️ لديك صفقة قيد المعالجة. يرجى الانتظار أو استخدام /cancel."
            )
            return ConversationHandler.END
        
        # Check daily limit
        can_trade, limit_info = self.sub_service.check_trade_limit(user_id)
        if not can_trade:
            await update.message.reply_text(
                f"❌ *تم بلوغ الحد اليومي للصفقات*\n\n"
                f"لقد استخدمت {limit_info['current']}/{limit_info['limit']} صفقة اليوم.\n"
                f"يُعاد ضبط الحد عند منتصف الليل UTC.\n\n"
                f"استخدم /upgrade لزيادة الحدود.",
                parse_mode=ParseMode.MARKDOWN
            )
            return ConversationHandler.END
        
        context.user_data['action'] = 'trade'
        context.user_data['trade_start'] = asyncio.get_running_loop().time()
        
        await update.message.reply_text(
            "📝 *أدخل إشارة الصفقة*\n\n"
            "استخدم التنسيق التالي:\n"
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
            "```",
            parse_mode=ParseMode.MARKDOWN
        )
        
        return ENTER_TRADE
    
    async def start_calculate(self, update: Update, context: CallbackContext) -> int:
        """Start the calculation flow (no execution)"""
        user_id = update.effective_user.id
        
        # Check if user is registered
        user = self.user_repo.get_by_telegram_id(user_id)
        if not user or not user.is_verified:
            await update.message.reply_text(
                "❌ يجب التسجيل أولًا!\n\nاستخدم /register لربط حساب MT5."
            )
            return ConversationHandler.END
        
        context.user_data['action'] = 'calculate'
        
        await update.message.reply_text(
            "📊 *أدخل بيانات الصفقة لحسابها*\n\n"
            "استخدم تنسيق /trade نفسه، ولن يتم تنفيذ الصفقة.\n\n"
            "```\n"
            "BUY/SELL [LIMIT/STOP] SYMBOL\n"
            "Entry PRICE أو NOW\n"
            "SL PRICE\n"
            "TP1 PRICE\n"
            "TP2 PRICE (اختياري)\n"
            "```",
            parse_mode=ParseMode.MARKDOWN
        )
        
        return ENTER_TRADE
    
    async def receive_trade(self, update: Update, context: CallbackContext) -> int:
        """Receive and parse trade signal"""
        user_id = update.effective_user.id
        signal_text = update.message.text
        
        # Store signal for later use
        context.user_data['signal_text'] = signal_text
        context.user_data['signal_external_id'] = (
            f"{update.effective_chat.id}:{update.message.message_id}"
        )
        
        # Show processing message
        processing_msg = await update.message.reply_text("🔄 جارٍ تحليل الإشارة...")
        context.user_data['processing_msg_id'] = processing_msg.message_id
        
        # Parse and calculate based on action
        if context.user_data['action'] == 'trade':
            return self._process_trade(update, context)
        else:
            return self._process_calculation(update, context)
    
    async def _process_trade(self, update: Update, context: CallbackContext) -> int:
        """Process a trade signal for execution"""
        user_id = update.effective_user.id
        signal_text = context.user_data['signal_text']
        
        # Mark as active
        self.active_trades[user_id] = context.user_data.get('trade_start')
        
        try:
            # Calculate trade first
            result = await self.trade_executor.calculate_only(user_id, signal_text)
            
            if not result['success']:
                await self._edit_message(
                    update, context,
                    f"❌ *إشارة غير صالحة*\n\nالخطأ: {result['error']}\n\nحاول مجددًا أو استخدم /cancel",
                    parse_mode=ParseMode.MARKDOWN
                )
                return ENTER_TRADE
            
            # Store calculation result
            context.user_data['calculation'] = result
            
            # Check if multiple TPs are allowed
            if len(result['signal']['take_profits']) > 1:
                has_feature = self.sub_service.check_feature_access(user_id, 'multiple_tps')
                if not has_feature:
                    # Show upgrade prompt
                    await self._edit_message(
                        update, context,
                        "⚠️ *تعدد مستويات جني الأرباح*\n\n"
                        "خطتك الحالية لا تدعم عدة مستويات لجني الأرباح.\n"
                        "سيُستخدم المستوى الأول فقط.\n\n"
                        "استخدم /upgrade لتفعيل هذه الميزة.",
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=get_trade_confirmation_keyboard(result)
                    )
                    return CONFIRM_TRADE
            
            # Show confirmation
            formatted = format_trade_calculation(result)
            
            # Use safe edit for the processing message
            msg_id = context.user_data.get('processing_msg_id')
            if msg_id:
                try:
                    await safe_edit_message(
                        update.callback_query if hasattr(update, 'callback_query') else None,
                        formatted,
                        parse_mode=ParseMode.HTML,
                        reply_markup=get_trade_confirmation_keyboard(result)
                    )
                except AttributeError:
                    # Not a callback query, use the edit_message method
                    await self._edit_message(
                        update, context,
                        formatted,
                        parse_mode=ParseMode.HTML,
                        reply_markup=get_trade_confirmation_keyboard(result)
                    )
            else:
                await self._edit_message(
                    update, context,
                    formatted,
                    parse_mode=ParseMode.HTML,
                    reply_markup=get_trade_confirmation_keyboard(result)
                )
            
            return CONFIRM_TRADE
            
        except Exception as exc:
            logger.error("Trade processing failed (%s)", type(exc).__name__)
            await self._edit_message(
                update, context,
                "❌ Error processing trade. Please try again or use /cancel."
            )
            return ENTER_TRADE
        finally:
            # Remove from active
            self.active_trades.pop(user_id, None)
    
    async def _process_calculation(self, update: Update, context: CallbackContext) -> int:
        """Process a calculation request"""
        user_id = update.effective_user.id
        signal_text = context.user_data['signal_text']
        
        try:
            result = await self.trade_executor.calculate_only(user_id, signal_text)
            
            if not result['success']:
                await self._edit_message(
                    update, context,
                    f"❌ *إشارة غير صالحة*\n\nالخطأ: {result['error']}",
                    parse_mode=ParseMode.MARKDOWN
                )
                return ConversationHandler.END
            
            # Format and send result
            formatted = format_trade_calculation(result, show_confirmation=False)
            await self._edit_message(
                update, context,
                f"{formatted}\nاستخدم /trade إذا أردت بدء مسار تنفيذ منفصل.",
                parse_mode=ParseMode.HTML
            )

            # A calculation is a terminal preview, never a trade confirmation.
            # Execution must be started explicitly through /trade.
            return ConversationHandler.END
            
        except Exception as exc:
            logger.error("Trade calculation failed (%s)", type(exc).__name__)
            await self._edit_message(update, context, "❌ تعذر حساب الإشارة. يرجى المحاولة لاحقًا.")
            return ConversationHandler.END
    
    async def confirm_trade(self, update: Update, context: CallbackContext) -> int:
        """Handle trade confirmation"""
        query = update.callback_query
        await query.answer()
        
        action = query.data.replace('trade_', '')
        
        if action == 'execute':
            # Execute the trade
            await query.edit_message_text("🔄 جارٍ تنفيذ الصفقة...")
            return await self._execute_trade(update, context)
        
        elif action == 'adjust':
            # Adjust risk
            await query.edit_message_text(
                "أدخل نسبة المخاطرة الجديدة (مثل 1.5 لتعيين 1.5%):"
            )
            return ADJUST_RISK
        
        elif action == 'cancel':
            # Cancel
            await query.edit_message_text("❌ تم إلغاء الصفقة.")
            context.user_data.clear()
            return ConversationHandler.END
        
        elif action == 'modify':
            # Modify trade parameters
            await query.edit_message_text(
                "أعد إدخال الصفقة بالبيانات المعدلة:"
            )
            return ENTER_TRADE
    
    async def _execute_trade(self, update: Update, context: CallbackContext) -> int:
        """Execute the confirmed trade"""
        user_id = update.effective_user.id

        if context.user_data.get('action') != 'trade':
            await self._edit_message(
                update, context,
                "❌ هذه معاينة فقط. ابدأ مسار التنفيذ باستخدام /trade."
            )
            return ConversationHandler.END

        calculation = context.user_data.get('calculation')
        
        if not calculation:
            await self._edit_message(
                update, context,
                "❌ فُقدت بيانات الصفقة. ابدأ من جديد باستخدام /trade"
            )
            return ConversationHandler.END
        
        try:
            # Execute trade
            result = await SignalPipeline(self.db, self.trade_executor).process(
                UnifiedSignal(source='manual', payload=context.user_data['signal_text'], user_id=user_id,
                              external_id=context.user_data.get('signal_external_id')),
                confirmed=True,
            )
            
            if result['success']:
                # Success message
                success_text = (
                    "✅ *Trade Executed Successfully!*\n\n"
                    f"📊 Position Size: {result['calculated']['position_size']}\n"
                    f"💰 Risk: ${result['calculated']['potential_loss']:,.2f}\n"
                    f"🎯 Target: ${result['calculated']['potential_profit']:,.2f}\n"
                    f"📈 R:R Ratio: 1:{result['calculated']['risk_reward']:.2f}\n\n"
                )
                
                if 'orders' in result:
                    order_ids = [o.get('orderId', 'N/A') for o in result['orders']]
                    success_text += f"معرّفات الأوامر: {', '.join(order_ids)}"
                
                await self._edit_message(
                    update, context,
                    success_text,
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                # Failure message
                await self._edit_message(
                    update, context,
                    f"❌ *Trade Failed*\n\nError: {result.get('error', 'Unknown error')}",
                    parse_mode=ParseMode.MARKDOWN
                )
            
        except Exception as exc:
            logger.error("Trade execution failed (%s)", type(exc).__name__)
            await self._edit_message(
                update, context,
                "❌ *Execution Error*\n\nThe request could not be completed.",
                parse_mode=ParseMode.MARKDOWN
            )
        
        # Clean up
        context.user_data.clear()
        return ConversationHandler.END
    
    async def adjust_risk(self, update: Update, context: CallbackContext) -> int:
        """Adjust risk percentage"""
        try:
            risk = float(update.message.text)
            risk_factor = risk / 100
            
            if risk_factor < 0.001 or risk_factor > 0.1:
                raise ValueError
            
            # Update calculation with new risk
            calculation = context.user_data.get('calculation')
            if not calculation or not context.user_data.get('signal_text'):
                raise ValueError

            user = self.user_repo.get_by_telegram_id(update.effective_user.id)
            if not user:
                raise ValueError
            previous_risk = user.default_risk_factor
            try:
                # calculate_only reads the user's risk factor but does not
                # commit it; restore the persisted preference after preview.
                user.default_risk_factor = risk_factor
                recalculated = await self.trade_executor.calculate_only(
                    update.effective_user.id,
                    context.user_data['signal_text'],
                )
            finally:
                user.default_risk_factor = previous_risk
                self.db.rollback()
            if not recalculated.get('success'):
                raise ValueError
            calculation = recalculated
            context.user_data['calculation'] = calculation
            
            # Show updated calculation
            from bot.keyboards import get_trade_confirmation_keyboard
            
            await update.message.reply_text(
                f"✅ Risk set to {risk:.1f}%\n\n"
                "راجع الحساب المحدّث:",
                reply_markup=get_trade_confirmation_keyboard(calculation)
            )
            
            return CONFIRM_TRADE
            
        except ValueError:
            await update.message.reply_text(
                "❌ Invalid percentage. Please enter a number between 0.1 and 10:"
            )
            return ADJUST_RISK
    
    async def handle_action(self, update: Update, context: CallbackContext) -> None:
        """Handle simple actions (balance, positions)"""
        user_id = update.effective_user.id
        action = context.user_data.get('action')
        
        if self.execution_provider is None:
        	await update.message.reply_text(
        	    "❌ Trading system is still starting up. Please wait a moment and try again."
        	)
        	context.user_data.clear()
        	return
        
        if not await self.wait_for_mt5_manager(timeout=30.0):
        	await update.message.reply_text(
        	    "❌ System is taking longer than expected to initialize.\n\n"
            "يرجى المحاولة بعد قليل. إذا استمرت المشكلة، تواصل مع الدعم."
        	)
        	context.user_data.clear()
        	return
        
        try:
            connection = await self.execution_provider.get_connection(user_id)
            
            if action == 'balance':
                account_info = await connection.get_account_information()
                formatted = format_balance(account_info)
                await update.message.reply_text(formatted, parse_mode=ParseMode.HTML)
            
            elif action == 'positions':
                positions = await connection.get_positions()
                if positions:
                    formatted = format_positions(positions)
                    await update.message.reply_text(formatted, parse_mode=ParseMode.HTML)
                else:
                    await update.message.reply_text("لا توجد صفقات مفتوحة.")
            
        except Exception as exc:
            logger.error("Action %s failed for user %s (%s)", action, user_id, type(exc).__name__)
            
            if "not registered" in str(exc).lower():
            	await update.message.reply_text(
            	    "❌ MT5 account not found. Please check your credentials in /settings"
            	)
            elif "not found" in str(exc).lower():
            	await update.message.reply_text(
            	    "❌ MT5 account not found. Please check your credentials in /settings"
            	)
            elif "timeout" in str(exc).lower():
            	await update.message.reply_text(
            	    "❌ Connection timeout. Please try again later."
            	)
            else:
            	await update.message.reply_text(
                f"❌ تعذر جلب {action}. يرجى المحاولة لاحقًا."
            	)
            	
        context.user_data.clear()
    
    async def _edit_message(self, update: Update, context: CallbackContext, 
                           text: str, **kwargs):
        """Edit the processing message or send new one"""
        msg_id = context.user_data.get('processing_msg_id')
        
        if msg_id:
            try:
                await context.bot.edit_message_text(
                    chat_id=update.effective_user.id,
                    message_id=msg_id,
                    text=text,
                    **kwargs
                )
            except:
                # If edit fails, send new message
                await context.bot.send_message(
                    chat_id=update.effective_user.id,
                    text=text,
                    **kwargs
                )
        else:
            await update.message.reply_text(text, **kwargs)
    
    async def cancel(self, update: Update, context: CallbackContext) -> int:
        """Cancel the current operation"""
        user_id = update.effective_user.id
        
        # Remove from active trades
        self.active_trades.pop(user_id, None)
        
        await update.message.reply_text(
            "❌ Operation cancelled."
        )
        
        context.user_data.clear()
        return ConversationHandler.END

    def get_states(self):
        """Return conversation states using bound instance methods"""
        # Defined after class so TradingHandler is in scope
        return  {
            ENTER_TRADE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.receive_trade)],
            CONFIRM_TRADE: [CallbackQueryHandler(self.confirm_trade, pattern='^trade_')],
            ADJUST_RISK: [MessageHandler(filters.TEXT, self.adjust_risk)],
            EXECUTING: [],
        }
