"""Shared authenticated ingress and durable idempotency for trading signals."""
import hashlib
import hmac
import json
import logging

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from config.settings import settings
from core.models import UnifiedSignal
from core.parser import SignalParser
from database.models import AdminSetting, SignalReceipt
from database.repositories import UserRepository
from services.subscription import SubscriptionService

logger = logging.getLogger(__name__)


class SignalPipeline:
    """Routes every inbound source through one normalization and policy path."""

    def __init__(self, db, executor):
        self.db = db
        self.executor = executor
        self.parser = SignalParser()
        self.users = UserRepository(db)
        self.subscriptions = SubscriptionService(db)

    @staticmethod
    def authenticate_tradingview(provided_secret):
        configured = getattr(settings, 'TRADINGVIEW_WEBHOOK_SECRET', None)
        return bool(configured and provided_secret and hmac.compare_digest(str(configured), str(provided_secret)))

    @staticmethod
    def authenticate_telegram_channel(chat_id):
        allowed = getattr(settings, 'TELEGRAM_SIGNAL_CHANNEL_IDS', []) or []
        return chat_id is not None and int(chat_id) in {int(item) for item in allowed}

    @staticmethod
    def normalize(unified):
        if not isinstance(unified, UnifiedSignal) or unified.source not in {'telegram_channel', 'tradingview', 'manual'}:
            raise ValueError('Unsupported signal envelope')
        if not isinstance(unified.payload, str):
            raise ValueError('Signal payload must be text')
        payload = unified.payload.strip()
        if not payload:
            raise ValueError('Empty signal payload')
        if unified.source == 'tradingview':
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                data = None
            if data is None:
                return UnifiedSignal(source=unified.source, payload=payload, user_id=unified.user_id,
                                     external_id=unified.external_id, received_at=unified.received_at,
                                     metadata=dict(unified.metadata))
            if not isinstance(data, dict):
                raise ValueError('TradingView payload must be a JSON object')
            action = str(data.get('action', data.get('side', ''))).upper()
            symbol = str(data.get('symbol', '')).upper().strip()
            sl = data.get('stop_loss', data.get('sl'))
            tps = data.get('take_profits', data.get('tp'))
            if isinstance(tps, (int, float, str)):
                tps = [tps]
            if action not in {'BUY', 'SELL'} or not symbol or sl is None or not tps:
                raise ValueError('TradingView payload requires action, symbol, stop_loss and take_profits')
            entry = data.get('entry')
            lines = [f'{action} {symbol}', f'Entry {"NOW" if entry is None else entry}', f'SL {sl}']
            # Preserve every requested target. Silently truncating a signal changes
            # its risk/execution intent and can hide a malformed overlong payload.
            lines.extend(f'TP{i} {tp}' for i, tp in enumerate(tps, 1))
            payload = '\n'.join(lines)
        return UnifiedSignal(source=unified.source, payload=payload, user_id=unified.user_id,
                             external_id=unified.external_id, received_at=unified.received_at,
                             metadata=dict(unified.metadata))

    def _claim(self, user, unified, signal):
        canonical = json.dumps(signal.to_dict() | {'metadata': {}}, sort_keys=True, separators=(',', ':'))
        external_id = str(unified.external_id or '')[:180]
        # Bounded deduplication allows a genuinely new identical setup later while
        # suppressing retries/reposts in the same five-minute signal window.
        time_bucket = int(unified.received_at.timestamp() // 300)
        source_key = external_id or hashlib.sha256(
            f'{canonical}:{time_bucket}'.encode()
        ).hexdigest()
        key = hashlib.sha256(f'{unified.source}:{source_key}'.encode()).hexdigest()
        receipt = SignalReceipt(user_id=user.id, source=unified.source, idempotency_key=key,
                                signal_text=unified.payload, status='received')
        self.db.add(receipt)
        try:
            self.db.commit()
            return receipt, False
        except IntegrityError:
            self.db.rollback()
            prior = self.db.query(SignalReceipt).filter_by(user_id=user.id, idempotency_key=key).first()
            return prior, True

    async def process(self, envelope, *, confirmed=False, existing_receipt=None):
        envelope = self.normalize(envelope)
        signal = self.parser.parse(envelope.payload, source=envelope.source)
        errors = signal.validate()
        if errors:
            return {'success': False, 'status': 'invalid', 'error': '; '.join(errors)}
        envelope.payload = self._render(signal)
        signal.metadata = {'source': envelope.source}
        if envelope.user_id is None:
            return {'success': False, 'status': 'unauthenticated', 'error': 'Signal target is required'}
        user = self.users.get_by_telegram_id(envelope.user_id)
        if not user or not user.is_active or not user.is_verified or user.is_banned:
            return {'success': False, 'status': 'unauthorized', 'error': 'Trading account is unavailable'}
        if user.allowed_symbols and signal.symbol not in user.allowed_symbols:
            return {'success': False, 'status': 'invalid', 'error': 'Symbol is not enabled for this account'}
        if signal.symbol in (user.blocked_symbols or []):
            return {'success': False, 'status': 'invalid', 'error': 'Symbol is blocked for this account'}

        if existing_receipt is not None:
            if existing_receipt.user_id != user.id:
                return {'success': False, 'status': 'unauthorized', 'error': 'Confirmation is not available'}
            # Claim the pending confirmation with a conditional DB write so two
            # simultaneous callback deliveries cannot execute the same receipt.
            claimed = self.db.query(SignalReceipt).filter(
                SignalReceipt.id == existing_receipt.id,
                SignalReceipt.user_id == user.id,
                SignalReceipt.status.in_(['manual_review', 'confirmation_required']),
            ).update({'status': 'processing'}, synchronize_session=False)
            self.db.commit()
            if claimed != 1:
                return {'success': False, 'status': 'already_processed',
                        'receipt_id': existing_receipt.id}
            receipt = self.db.query(SignalReceipt).filter_by(
                id=existing_receipt.id
            ).populate_existing().first()
            duplicate = False
        else:
            receipt, duplicate = self._claim(user, envelope, signal)
            if duplicate:
                return {'success': False, 'status': 'duplicate', 'receipt_id': receipt.id}
        can_trade, limit = self.subscriptions.check_trade_limit(envelope.user_id)
        if not can_trade:
            receipt.status = 'rejected_subscription'
            self.db.commit()
            return {'success': False, 'status': 'limit_reached', 'limit_info': limit}

        mode = user.trade_mode or 'manual'
        if mode not in {'manual', 'semi_auto', 'auto'}:
            receipt.status = 'rejected_mode'
            self.db.commit()
            return {'success': False, 'status': 'rejected_mode', 'error': 'Invalid trade mode'}
        if envelope.source != 'manual' and mode == 'manual' and not confirmed:
            receipt.status = 'manual_review'
            self.db.commit()
            await self._request_confirmation(envelope.user_id, receipt.id)
            return {'success': False, 'status': 'manual_review', 'receipt_id': receipt.id}
        if envelope.source != 'manual' and mode == 'semi_auto' and not confirmed:
            receipt.status = 'confirmation_required'
            self.db.commit()
            await self._request_confirmation(envelope.user_id, receipt.id)
            return {'success': False, 'status': 'confirmation_required', 'receipt_id': receipt.id}
        if mode == 'auto' and not self.subscriptions.check_feature_access(envelope.user_id, 'auto_trading'):
            receipt.status = 'rejected_subscription'
            self.db.commit()
            return {'success': False, 'status': 'subscription_required', 'error': 'Auto trading is not included in this plan'}
        if envelope.source == 'manual' and not confirmed:
            receipt.status = 'confirmation_required'
            self.db.commit()
            return {'success': False, 'status': 'confirmation_required', 'receipt_id': receipt.id}

        # The explicit kill switch is checked after authentication and policy checks;
        # no gateway/account connection or mutating request is made in dry-run mode.
        if getattr(settings, 'TRADING_DRY_RUN', True):
            receipt.status = 'dry_run'
            self.db.commit()
            mode = 'demo'
            try:
                u = self.users.get_by_telegram_id(envelope.user_id) if hasattr(self, 'users') else None
                if u is not None:
                    mode = getattr(u, 'trading_mode', None) or 'demo'
            except Exception:
                mode = 'demo'
            return {'success': False, 'status': 'dry_run', 'error': 'Trading is disabled in dry-run mode',
                    'receipt_id': receipt.id, 'signal': signal.to_dict(), 'user_trading_mode': mode}

        # Fail closed if the persistent emergency-stop state is unavailable.
        try:
            emergency_state = self.db.query(AdminSetting).filter_by(
                key='emergency_stop'
            ).first()
        except Exception:
            self.db.rollback()
            receipt.status = 'blocked_emergency_state_unavailable'
            self.db.commit()
            return {'success': False, 'status': 'blocked',
                    'error': 'Emergency stop state is unavailable'}
        if emergency_state and emergency_state.value.lower() == 'true':
            receipt.status = 'blocked_emergency_stop'
            self.db.commit()
            return {'success': False, 'status': 'blocked',
                    'error': 'Emergency stop is active'}

        try:
            result = await self.executor.execute_trade(envelope.user_id, envelope.payload,
                                                       {'source': envelope.source, 'receipt_id': receipt.id})
            receipt.status = result.get('status', 'unknown')
            receipt.trade_uuid = result.get('trade_id')
            self.db.commit()
            return result
        except Exception:
            self.db.rollback()
            logger.exception('Unified signal processing failed')
            return {'success': False, 'status': 'unknown', 'error': 'Signal processing result is unknown'}

    async def confirm(self, telegram_user_id, receipt_id):
        user = self.users.get_by_telegram_id(telegram_user_id)
        receipt = self.db.query(SignalReceipt).filter_by(id=receipt_id).first()
        if not user or not receipt or receipt.user_id != user.id:
            return {'success': False, 'status': 'unauthorized'}
        envelope = UnifiedSignal(source=receipt.source, payload=receipt.signal_text,
                                 user_id=telegram_user_id)
        return await self.process(envelope, confirmed=True, existing_receipt=receipt)

    async def cancel(self, telegram_user_id, receipt_id):
        user = self.users.get_by_telegram_id(telegram_user_id)
        receipt = self.db.query(SignalReceipt).filter_by(id=receipt_id).first()
        if not user or not receipt or receipt.user_id != user.id or receipt.status not in {
                'manual_review', 'confirmation_required'}:
            return {'success': False, 'status': 'unauthorized'}
        receipt.status = 'cancelled'
        self.db.commit()
        return {'success': True, 'status': 'cancelled'}

    @staticmethod
    def _render(signal):
        entry = 'NOW' if signal.entry is None else str(signal.entry)
        lines = [f'{signal.order_type.value} {signal.symbol}', f'Entry {entry}',
                 f'SL {signal.stop_loss}']
        lines.extend(f'TP{i} {tp}' for i, tp in enumerate(signal.take_profits, 1))
        return '\n'.join(lines)

    async def _request_confirmation(self, telegram_user_id, receipt_id):
        bot = getattr(self.executor, 'bot', None)
        if not bot:
            return
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(
            'تأكيد المعالجة', callback_data=f'signal_confirm:{receipt_id}')], [InlineKeyboardButton(
            'إلغاء', callback_data=f'signal_cancel:{receipt_id}')]])
        receipt = self.db.query(SignalReceipt).filter_by(id=receipt_id).first()
        signal_text = receipt.signal_text if receipt else ''
        try:
            await bot.send_message(chat_id=telegram_user_id,
                                   text=f'إشارة جديدة:\n{signal_text}\n\nراجعها وأكد رغبتك في المتابعة.',
                                   reply_markup=keyboard)
        except Exception:
            logger.error('Could not send signal confirmation prompt to user %s', telegram_user_id)
