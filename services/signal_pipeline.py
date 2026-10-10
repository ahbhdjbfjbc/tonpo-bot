"""Shared authenticated ingress and durable idempotency for trading signals."""
import hashlib
import hmac
import json
import logging
import time

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from config.settings import settings
from core.models import UnifiedSignal
from core.parser import SignalParser
from database.models import AdminSetting, SignalReceipt
from database.repositories import UserRepository
from services.subscription import SubscriptionService
from services.news_protection import NewsProtectionService
from services.protection import ProtectionService
from services.notification import NotificationService
from services.signal_time import validate_signal_timestamp

logger = logging.getLogger(__name__)


class SignalPipeline:
    """Routes every inbound source through one normalization and policy path."""

    def __init__(self, db, executor):
        self.db = db
        self.executor = executor
        self.parser = SignalParser()
        self.users = UserRepository(db)
        self.subscriptions = SubscriptionService(db)
        self.news = NewsProtectionService()
        self.protection = ProtectionService(db)
        self.notifications = NotificationService(db, getattr(executor, "bot", None))

    @staticmethod
    def _reject(receipt, status: str, reason: str, *, news_status: str | None = None) -> dict:
        receipt.status = status
        receipt.rejection_reason = reason[:255]
        if news_status is not None:
            receipt.news_status = news_status
        return {'success': False, 'status': status, 'error': reason, 'receipt_id': receipt.id}

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
        receipt = SignalReceipt(
            user_id=user.id, source=unified.source, idempotency_key=key,
            signal_text=unified.payload, status='received',
            validation_status='passed', signal_id=external_id or key,
            account_id=getattr(user, 'gateway_account_id', None) or getattr(user, 'gateway_user_id', None),
            direction=getattr(signal, 'direction', None), entry_price=signal.entry,
            stop_loss=signal.stop_loss, take_profits=list(signal.take_profits),
            signal_timestamp=unified.received_at.replace(tzinfo=None),
        )
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
        signal.metadata = {**dict(envelope.metadata or {}), 'source': envelope.source}
        if envelope.user_id is None:
            return {'success': False, 'status': 'unauthenticated', 'error': 'Signal target is required'}
        user = self.users.get_by_telegram_id(envelope.user_id)
        if not user or not user.is_active or not user.is_verified or user.is_banned:
            return {'success': False, 'status': 'unauthorized', 'error': 'Trading account is unavailable'}
        if existing_receipt is not None and existing_receipt.user_id != user.id:
            return {'success': False, 'status': 'unauthorized', 'error': 'Confirmation is not available'}
        timestamp_value = (envelope.metadata or {}).get('timestamp')
        if timestamp_value is None:
            timestamp_value = envelope.received_at
        signal_time, time_status = validate_signal_timestamp(
            timestamp_value,
            max_age_seconds=getattr(settings, 'MAX_SIGNAL_AGE_SECONDS', 300),
            max_future_skew_seconds=getattr(settings, 'MAX_FUTURE_SIGNAL_SKEW_SECONDS', 30),
        )
        if time_status:
            if (
                time_status == 'stale_signal'
                and existing_receipt is not None
                and existing_receipt.status in {'manual_review', 'confirmation_required'}
            ):
                existing_receipt.status = 'expired'
                existing_receipt.rejection_reason = 'Signal confirmation window expired'
                self.db.commit()
            messages = {
                'stale_signal': 'Signal is older than the configured acceptance window',
                'future_signal': 'Signal timestamp is too far in the future',
                'invalid_timestamp': 'Signal timestamp is invalid',
            }
            return {'success': False, 'status': time_status, 'error': messages[time_status]}
        envelope.received_at = signal_time.replace(tzinfo=None)
        if existing_receipt is not None:
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
                if receipt.status == 'unknown':
                    return {'success': False, 'status': 'unknown', 'error': 'Execution state is unknown; reconciliation is required', 'receipt_id': receipt.id, 'reconciliation_required': True}
                return {'success': False, 'status': 'duplicate', 'receipt_id': receipt.id}

        if user.allowed_symbols and signal.symbol not in user.allowed_symbols:
            result = self._reject(receipt, 'invalid', 'Symbol is not enabled for this account')
            self.db.commit()
            return result
        if signal.symbol in (user.blocked_symbols or []):
            result = self._reject(receipt, 'invalid', 'Symbol is blocked for this account')
            self.db.commit()
            return result

        news = self.news.assess(signal.symbol)
        receipt.news_status = news['status']
        receipt.final_decision = 'rejected' if news['status'] in {'active', 'unavailable', 'stale'} else None
        if news['status'] == 'active':
            result = self._reject(receipt, 'news_blocked', news['reason'], news_status='active')
            receipt.protection_reason = news['reason'][:255]
            self.db.commit()
            await self.notifications.notify_event(envelope.user_id, 'signal_rejected', title='Signal rejected', message=news['reason'], data={'signal_id': receipt.signal_id, 'reason': news['reason']}, event_key=f'signal:{receipt.id}:news')
            return result
        if news['status'] == 'unavailable':
            result = self._reject(receipt, 'news_unavailable', news['reason'], news_status='unavailable')
            receipt.protection_reason = news['reason'][:255]
            self.db.commit()
            await self.notifications.notify_event(envelope.user_id, 'signal_rejected', title='Signal rejected', message=news['reason'], data={'signal_id': receipt.signal_id, 'reason': news['reason']}, event_key=f'signal:{receipt.id}:news')
            return result
        if news['status'] == 'stale':
            result = self._reject(receipt, 'news_stale', news['reason'], news_status='stale')
            receipt.protection_reason = news['reason'][:255]
            self.db.commit()
            await self.notifications.notify_event(envelope.user_id, 'signal_rejected', title='Signal rejected', message=news['reason'], data={'signal_id': receipt.signal_id, 'reason': news['reason']}, event_key=f'signal:{receipt.id}:news')
            return result
        protection = self.protection.evaluate(user, signal)
        receipt.risk_status = 'passed' if protection['allowed'] else 'blocked'
        receipt.risk_reason = protection['reason'][:255]
        if not protection['allowed']:
            receipt.final_decision = 'rejected'
            receipt.status = 'risk_blocked'
            receipt.rejection_reason = protection['reason'][:255]
            receipt.protection_reason = protection['reason'][:255]
            self.db.commit()
            await self.notifications.notify_event(envelope.user_id, 'signal_rejected', title='Signal rejected', message=protection['reason'], data={'signal_id': receipt.signal_id, 'reason_code': protection['code']}, event_key=f'signal:{receipt.id}:protection')
            return {'success': False, 'status': 'blocked' if protection['code'] == 'kill_switch' else 'risk_blocked', 'error': protection['reason'], 'reason_code': protection['code'], 'receipt_id': receipt.id}

        can_trade, limit = self.subscriptions.check_trade_limit(envelope.user_id)
        if not can_trade:
            receipt.status = 'rejected_subscription'
            receipt.rejection_reason = 'Daily subscription trade limit reached'
            self.db.commit()
            return {'success': False, 'status': 'limit_reached', 'limit_info': limit}

        mode = user.trade_mode or 'manual'
        if mode not in {'manual', 'semi_auto', 'auto'}:
            receipt.status = 'rejected_mode'
            receipt.rejection_reason = 'Trading mode is invalid'
            self.db.commit()
            return {'success': False, 'status': 'rejected_mode', 'error': 'Invalid trade mode'}
        if not bool(getattr(settings, 'TRADING_DRY_RUN', True)) and (user.trading_mode or 'demo') != 'live':
            receipt.status = 'rejected_account_mode'
            receipt.rejection_reason = 'Live broker execution requires the user account to be in live mode'
            self.db.commit()
            return {
                'success': False,
                'status': 'account_mode_blocked',
                'error': 'Live execution requires the account trading mode to be live',
                'receipt_id': receipt.id,
            }
        if mode == 'auto' and not bool(getattr(settings, 'ENABLE_AUTO_TRADING', True)):
            receipt.status = 'rejected_auto_trading_disabled'
            receipt.rejection_reason = 'Automatic trading is disabled by server policy'
            self.db.commit()
            return {
                'success': False,
                'status': 'auto_trading_disabled',
                'error': 'Automatic trading is disabled by server policy',
                'receipt_id': receipt.id,
            }
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
            receipt.rejection_reason = 'Auto trading is not included in this subscription'
            self.db.commit()
            return {'success': False, 'status': 'subscription_required', 'error': 'Auto trading is not included in this plan'}
        if envelope.source == 'manual' and not confirmed:
            receipt.status = 'confirmation_required'
            self.db.commit()
            return {'success': False, 'status': 'confirmation_required', 'receipt_id': receipt.id}

        receipt.final_decision = 'accepted'
        receipt.status = 'execution'
        self.db.commit()

        # Execution always crosses the single TradeExecutor boundary.
        # TradeExecutor enforces TRADING_DRY_RUN before any broker/provider access.

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
            started = time.perf_counter()
            result = await self.executor.execute_trade(envelope.user_id, envelope.payload,
                                                       {'source': envelope.source, 'receipt_id': receipt.id})
            receipt.execution_latency_ms = round((time.perf_counter() - started) * 1000, 3)
            receipt.status = result.get('status', 'unknown')
            receipt.trade_uuid = result.get('trade_id')
            receipt.final_decision = 'executed' if result.get('success') else 'failed' if result.get('status') != 'unknown' else 'unknown'
            if not result.get('success') and result.get('error'):
                receipt.rejection_reason = str(result['error'])[:255]
            self.db.commit()
            event = 'signal_executed' if result.get('success') else 'execution_unknown' if result.get('status') == 'unknown' else 'execution_failed'
            await self.notifications.notify_event(envelope.user_id, event, title='Signal decision', message=str(result.get('error') or result.get('status') or 'Execution result'), data={'signal_id': receipt.signal_id, 'status': receipt.status}, event_key=f'signal:{receipt.id}:result')
            if result.get('success') and result.get('status') == 'executed' and not getattr(settings, 'TRADING_DRY_RUN', True):
                await self.notifications.publish_trade_execution(receipt.id, result)
            return result
        except Exception as exc:
            self.db.rollback()
            logger.error('Unified signal processing failed (%s)', type(exc).__name__)
            return {'success': False, 'status': 'unknown', 'error': 'Signal processing result is unknown'}

    async def confirm(self, telegram_user_id, receipt_id):
        user = self.users.get_by_telegram_id(telegram_user_id)
        receipt = self.db.query(SignalReceipt).filter_by(id=receipt_id).first()
        if not user or not receipt or receipt.user_id != user.id:
            return {'success': False, 'status': 'unauthorized'}
        signal_time = receipt.signal_timestamp or receipt.created_at
        envelope = UnifiedSignal(
            source=receipt.source,
            payload=receipt.signal_text,
            user_id=telegram_user_id,
            received_at=signal_time,
            metadata={'timestamp': signal_time.isoformat()} if signal_time else {},
        )
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
