# fx/services/trade_executor.py
"""
Trade executor service.
"""
import asyncio
from typing import Dict, Any, Optional, List
from datetime import datetime
import logging
import traceback
from sqlalchemy import inspect as sqlalchemy_inspect
from sqlalchemy.orm import Session

from core.models import TradeSignal, CalculatedTrade, UnifiedSignal
from services.signal_processor import SignalProcessor
#from core.parser import SignalParser
from services.risk_service import RiskService
from services.protection import ProtectionService
from services.subscription import SubscriptionService
from services.notification import NotificationService
from database.repositories import TradeRepository, UserRepository
from database.models import Trade
from config.settings import settings
from gateway_client.adapter import GatewayCapabilityUnavailable

logger = logging.getLogger(__name__)


class TradeExecutionError(Exception):
    """Raised when trade execution fails"""
    pass


class TradeExecutor:
    def __init__(self, db_session: Session, bot=None, mt5_manager=None, execution_provider=None):
        self.db = db_session
        self.bot = bot
        
        # Initialize services
        self.signal_processor = SignalProcessor()
        #self.signal_processor = SignalParser()
        
        self.risk_service = RiskService()
        self.protection = ProtectionService(db_session)
        self.sub_service = SubscriptionService(db_session)
        self.notification = NotificationService(db_session, bot)
        self.trade_repo = TradeRepository(db_session)
        self.user_repo = UserRepository(db_session)
        
        # Execution provider (preferred) or direct mt5_manager (legacy fallback)
        self.execution_provider = execution_provider
        self.mt5_manager = mt5_manager
        
        # Track in-progress trades
        self.pending_trades = {}
    
    async def _get_connection(self, user_id: int):
        """
        Get a connection through ExecutionProvider (preferred) or mt5_manager (fallback).
        This is the single point where all connection routing happens.
        """
        if self.execution_provider:
            return await self.execution_provider.get_connection(user_id)
        elif self.mt5_manager:
            return await self.mt5_manager.get_connection(user_id)
        else:
            raise TradeExecutionError("No execution provider or MT5 manager available")
    
    async def execute_trade(self, user_id: int, signal_text: str, 
                           context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Execute a trade from signal text
        """
        if getattr(settings, 'TRADING_DRY_RUN', True):
            logger.warning("Trade execution blocked by TRADING_DRY_RUN")
            return {'success': False, 'error': 'Trading is disabled in dry-run mode', 'status': 'dry_run'}
        # Every broker leg/result must be durable before an order can be sent.
        # In particular, older installations may not yet have migration 014's
        # execution_results column; discovering that only after placement would
        # leave an accepted order with no persisted per-leg outcome.
        try:
            bind = self.db.get_bind()
            inspector = sqlalchemy_inspect(bind)
            schema_ready = inspector.has_table('trades') and 'execution_results' in {
                column['name'] for column in inspector.get_columns('trades')
            }
        except Exception:
            schema_ready = False
        if not schema_ready:
            logger.error("Trade execution blocked: result persistence schema is unavailable")
            return {
                'success': False,
                'error': 'Trade result persistence is unavailable; database upgrade is required.',
                'status': 'blocked_schema',
            }
        user = self.user_repo.get_by_telegram_id(user_id)
        if not user:
            return {'success': False, 'error': 'User not found', 'status': 'user_not_found'}
        if (user.trading_mode or 'demo') != 'live':
            logger.warning("Trade execution blocked: user %s is not in live mode", user_id)
            return {
                'success': False,
                'error': 'Live execution requires the account trading mode to be live',
                'status': 'account_mode_blocked',
            }
        # Check if user already has a trade in progress
        if user_id in self.pending_trades:
            return {
                'success': False,
                'error': 'Trade already in progress',
                'status': 'pending_exists'
            }
        
        # Mark as pending
        self.pending_trades[user_id] = {
            'started_at': datetime.utcnow(),
            'signal': signal_text
        }
        trade_record = None
        results = []
        reserved_at = None
        broker_mutation_started = False
        try:
            # Step 1: Parse signal
            logger.info(f"Parsing signal for user {user_id}")
            signal = self.signal_processor.process(signal_text)
            
            # Step 2: Check subscription limits
            can_trade, limit_info = self.sub_service.check_trade_limit(user_id)
            if not can_trade:
                await self.notification.notify_daily_limit(user_id, limit_info['limit'])
                return {
                    'success': False,
                    'error': 'Daily trade limit reached',
                    'limit_info': limit_info,
                    'status': 'limit_reached'
                }
            
            # Step 3: Get connection via ExecutionProvider
            connection = await self._get_connection(user_id)
            account_info = await connection.get_account_information()
            get_positions = getattr(connection, 'get_positions', None)
            if get_positions is None:
                return {
                    'success': False,
                    'error': 'Broker positions are unavailable; execution is blocked.',
                    'status': 'risk_blocked',
                    'reason_code': 'positions_unavailable',
                }
            try:
                positions = await get_positions()
            except Exception:
                return {
                    'success': False,
                    'error': 'Broker positions are unavailable; execution is blocked.',
                    'status': 'risk_blocked',
                    'reason_code': 'positions_unavailable',
                }
            account_limits = self.protection.evaluate_account_limits(user, account_info, positions)
            if not account_limits['allowed']:
                return {
                    'success': False,
                    'error': account_limits['reason'],
                    'status': 'risk_blocked',
                    'reason_code': account_limits['code'],
                }
            
            # Step 5: Market preflight; never risk or send an order without a valid quote.
            price = await connection.get_symbol_price(signal.symbol)
            bid, ask = float(price.get('bid', 0)), float(price.get('ask', 0))
            if not (0 < bid < ask):
                raise TradeExecutionError('Broker returned invalid market prices')
            max_spread = getattr(user.settings, 'max_spread', None) if user.settings else None
            if max_spread and ask - bid > float(max_spread):
                raise TradeExecutionError('Broker spread exceeds the account limit')
            if signal.is_market_order and signal.entry is None:
                signal.entry = ask if signal.is_buy else bid
            validation_errors = signal.validate()
            if validation_errors:
                raise TradeExecutionError('; '.join(validation_errors))

            # This Tonpo SDK version exposes quotes and positions but no symbol contract
            # metadata. Fail closed instead of inventing lot/tick constraints.
            get_constraints = getattr(connection, 'get_symbol_constraints', None)
            if get_constraints is None:
                return {
                    'success': False,
                    'error': 'Broker symbol constraints are unavailable; execution is blocked.',
                    'status': 'blocked_constraints',
                }
            try:
                broker_constraints = await get_constraints(signal.symbol)
            except GatewayCapabilityUnavailable:
                return {
                    'success': False,
                    'error': 'Broker symbol constraints are unavailable; execution is blocked.',
                    'status': 'blocked_constraints',
                }
            if not broker_constraints:
                return {
                    'success': False,
                    'error': 'Broker symbol constraints are unavailable; execution is blocked.',
                    'status': 'blocked_constraints',
                }
            
            # Step 6: Calculate risk
            user_settings = {
                'default_risk_factor': user.default_risk_factor,
                'max_position_size': user.max_position_size,
                'symbol_risk_overrides': user.settings.symbol_risk_overrides if user.settings else {}
            }
            
            calculated = self.risk_service.calculate_trade(
                signal=signal,
                balance=account_info['balance'],
                risk_factor=user.default_risk_factor,
                user_settings=user_settings,
                broker_constraints=broker_constraints,
            )
            
            # Step 7: Check position size limit
            size_check, size_message = self.sub_service.check_position_size_limit(
                user_id, calculated.position_size
            )
            if not size_check:
                return {
                    'success': False,
                    'error': size_message,
                    'status': 'size_limit'
                }
            
            # Step 8: Check feature access (multiple TPs)
            if len(signal.take_profits) > 1:
                has_multiple_tps = self.sub_service.check_feature_access(user_id, 'multiple_tps')
                if not has_multiple_tps:
                    # Use only first TP
                    signal.take_profits = [signal.take_profits[0]]
                    calculated = self.risk_service.calculate_trade(
                        signal=signal,
                        balance=account_info['balance'],
                        risk_factor=user.default_risk_factor,
                        user_settings=user_settings,
                        broker_constraints=broker_constraints,
                    )
            
            # Step 9: Check for duplicates
            is_duplicate = self.signal_processor.is_duplicate(
                signal, 
                self._get_recent_signals(user_id)
            )
            if is_duplicate:
                return {
                    'success': False,
                    'error': 'Duplicate signal detected',
                    'status': 'duplicate'
                }

            # The earlier limit check is informational. Reserve with a conditional
            # database update immediately before creating the durable intent so
            # concurrent workers cannot both consume the final slot.
            can_reserve, reservation = self.sub_service.reserve_trade_slot(user_id)
            if not can_reserve:
                return {
                    'success': False,
                    'error': 'Daily trade limit reached',
                    'limit_info': reservation,
                    'status': 'limit_reached',
                }
            reserved_at = reservation['reserved_at']
            
            # Step 10: Persist a durable intent before any broker mutation.
            # If the broker call later times out or raises, reconciliation has a
            # concrete Tonpo record instead of an untracked external side effect.
            trade_record = Trade(
                user_id=user.id,
                order_type=signal.order_type.value,
                symbol=signal.symbol,
                entry_price=signal.entry,
                stop_loss=signal.stop_loss,
                take_profits=signal.take_profits,
                position_size=calculated.position_size,
                risk_percentage=calculated.risk_percentage,
                risk_amount=calculated.potential_loss,
                potential_reward=calculated.total_potential_profit,
                mt_order_ids=[],
                execution_results=[],
                status='pending',
                signal_text=signal_text,
                signal_hash=self.signal_processor._calculate_hash(signal_text),
            )
            self.db.add(trade_record)
            self.db.commit()

            logger.info(f"Executing trade for user {user_id}: {signal}")
            
            trade_data = {
                'order_type': signal.order_type.value,
                'symbol': signal.symbol,
                'volume': calculated.position_size,
                'stop_loss': signal.stop_loss,
                'take_profit': signal.take_profits[0]  # First TP for execution
            }
            
            # For multiple TPs, we need to split
            if len(signal.take_profits) > 1:
                step = float(broker_constraints['volume_step'])
                units = round(calculated.position_size / step)
                base_units, remainder = divmod(units, len(signal.take_profits))
                tp_volumes = [((base_units + (1 if i < remainder else 0)) * step)
                              for i in range(len(signal.take_profits))]
                if min(tp_volumes) < float(broker_constraints['volume_min']):
                    raise TradeExecutionError('Position is too small to split across the requested targets')

                for tp, tp_volume in zip(signal.take_profits, tp_volumes):
                    trade_data['volume'] = tp_volume
                    trade_data['take_profit'] = tp
                    
                    if signal.order_type.value in ['Buy', 'Sell']:
                        broker_mutation_started = True
                        result = await self._execute_market_order(connection, trade_data)
                    else:
                        trade_data['price'] = signal.entry
                        broker_mutation_started = True
                        result = await self._execute_pending_order(connection, trade_data)
                    
                    results.append(result)
                    # Never submit another leg after an ambiguous broker result.
                    if result.get('status') in {'unknown', 'timeout'} or (
                        not result.get('success') and result.get('status') not in {'rejected'}
                    ):
                        break
            else:
                # Single TP execution
                if signal.order_type.value in ['Buy', 'Sell']:
                    broker_mutation_started = True
                    result = await self._execute_market_order(connection, trade_data)
                else:
                    trade_data['price'] = signal.entry
                    broker_mutation_started = True
                    result = await self._execute_pending_order(connection, trade_data)
                
                results = [result]

            # A success flag from an order request is an acknowledgement, not proof
            # that a market position exists. Pending orders remain pending by design.
            if signal.is_pending_order:
                accepted = [bool(r.get('success') and r.get('orderId')) for r in results]
                all_rejected = all(r.get('status') == 'rejected' for r in results)
                execution_status = ('failed' if all_rejected else 'pending' if all(accepted) else
                                    'partial' if any(accepted) else 'unknown')
            else:
                verified = []
                for order_result in results:
                    if not order_result.get('success') or not order_result.get('orderId'):
                        verified.append(False)
                        continue
                    verifier = getattr(connection, 'verify_market_execution', None)
                    if verifier is None:
                        verified.append(False)
                        continue
                    try:
                        verified.append(bool(await verifier(order_result['orderId'])))
                    except Exception:
                        verified.append(False)
                all_rejected = all(r.get('status') == 'rejected' for r in results)
                execution_status = ('failed' if all_rejected else 'executed' if all(verified) else
                                    'partial' if any(verified) else 'unknown')
            
            # Step 11: Finalize the durable intent with broker evidence.
            trade_record.mt_order_ids = [r.get('orderId') for r in results if r.get('orderId')]
            trade_record.execution_results = results
            trade_record.status = execution_status
            trade_record.executed_at = datetime.utcnow() if execution_status == 'executed' else None

            # A pending order consumes the submission slot but is not counted as
            # a completed trade. Unknown/partial outcomes keep the slot for reconciliation.
            if execution_status == 'executed':
                self.sub_service.record_trade_statistics(user_id, calculated.position_size)
            elif execution_status == 'failed' and reserved_at is not None:
                self.sub_service.release_trade_slot(user_id, reserved_at)
            
            self.db.commit()
            
            # Notification failure must never rewrite an already persisted broker result.
            try:
                if execution_status == 'executed':
                    await self.notification.notify_trade_executed(user_id, {
                        'order_type': signal.order_type.value,
                        'symbol': signal.symbol,
                        'size': calculated.position_size,
                        'risk': calculated.potential_loss,
                        'reward': calculated.total_potential_profit,
                        'rr_ratio': calculated.risk_reward_ratio
                    })
                elif execution_status in {'unknown', 'partial'}:
                    await self.notification.send_telegram(
                        user_id, f"نتيجة الصفقة {execution_status}: راجع حالة الأوامر لدى الوسيط قبل إعادة المحاولة."
                    )
                elif execution_status == 'pending':
                    await self.notification.send_telegram(
                        user_id, "تم قبول الأمر المعلق لدى الوسيط؛ حالته الحالية pending."
                    )
                elif execution_status == 'failed':
                    await self.notification.notify_trade_failed(
                        user_id, 'Broker rejected the order', {'symbol': signal.symbol}
                    )
            except Exception:
                logger.error("Trade result notification failed for user %s", user_id)
            
            logger.info("Trade processing completed for user %s with status %s", user_id, execution_status)
            
            return {
                'success': execution_status in {'executed', 'pending'},
                'trade_id': trade_record.uuid,
                'signal': {
                    'order_type': signal.order_type.value,
                    'symbol': signal.symbol,
                    'entry': signal.entry,
                    'stop_loss': signal.stop_loss,
                    'take_profits': signal.take_profits
                },
                'calculated': {
                    'position_size': calculated.position_size,
                    'risk_percentage': calculated.risk_percentage,
                    'potential_loss': calculated.potential_loss,
                    'potential_profit': calculated.total_potential_profit,
                    'risk_reward': calculated.risk_reward_ratio
                },
                'orders': results,
                'status': execution_status
            }
            
        except Exception as exc:
            self.db.rollback()
            if not broker_mutation_started:
                # No order request was ever sent, so it is safe to release the
                # reservation and mark any durable intent as failed, not unknown.
                try:
                    if reserved_at is not None:
                        self.sub_service.release_trade_slot(user_id, reserved_at)
                        self.db.commit()
                    if trade_record is not None and getattr(trade_record, 'id', None) is not None:
                        persisted = self.db.query(Trade).filter_by(id=trade_record.id).one()
                        persisted.status = 'failed'
                        persisted.error_message = 'Execution failed before broker submission.'
                        self.db.commit()
                except Exception:
                    self.db.rollback()
                try:
                    await self.notification.notify_trade_failed(
                        user_id, 'Trade was not submitted to the broker', {'signal': signal_text[:100]}
                    )
                except Exception:
                    logger.error("Could not notify user %s about pre-submission failure", user_id)
                return {
                    'success': False,
                    'error': 'Trade could not be submitted; no broker order was sent.',
                    'status': 'failed',
                }
            if trade_record is not None and getattr(trade_record, 'id', None) is not None:
                try:
                    persisted = self.db.query(Trade).filter_by(id=trade_record.id).one()
                    persisted.status = 'unknown'
                    persisted.execution_results = results
                    persisted.error_message = 'Execution outcome unknown; reconciliation required.'
                    self.db.commit()
                except Exception:
                    self.db.rollback()
            frames = traceback.extract_tb(exc.__traceback__)
            error_location = (
                f"{frames[-1].filename}:{frames[-1].lineno}:{frames[-1].name}"
                if frames else "unknown"
            )
            logger.error(
                "Trade execution outcome unknown for user %s (exception_type=%s, location=%s)",
                user_id,
                type(exc).__name__,
                error_location,
            )
            try:
                await self.notification.notify_trade_failed(user_id, 'Execution status unknown', {
                    'signal': signal_text[:100]
                })
            except Exception:
                logger.error("Could not notify user %s about unknown execution outcome", user_id)
            
            return {
                'success': False,
                'error': 'Execution outcome unknown; verify with the broker before retrying.',
                'status': 'unknown'
            }
            
        finally:
            # Remove from pending
            self.pending_trades.pop(user_id, None)
    
    async def _execute_market_order(self, connection, trade_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a market order"""
        if trade_data['order_type'] == 'Buy':
            return await connection.create_market_buy_order(
                trade_data['symbol'],
                trade_data['volume'],
                trade_data['stop_loss'],
                trade_data['take_profit']
            )
        else:
            return await connection.create_market_sell_order(
                trade_data['symbol'],
                trade_data['volume'],
                trade_data['stop_loss'],
                trade_data['take_profit']
            )
    
    async def _execute_pending_order(self, connection, trade_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a pending order (limit/stop)"""
        order_map = {
            'Buy Limit': connection.create_limit_buy_order,
            'Sell Limit': connection.create_limit_sell_order,
            'Buy Stop': connection.create_stop_buy_order,
            'Sell Stop': connection.create_stop_sell_order
        }
        
        order_func = order_map.get(trade_data['order_type'])
        if not order_func:
            raise TradeExecutionError(f"Unsupported order type: {trade_data['order_type']}")
        
        return await order_func(
            trade_data['symbol'],
            trade_data['volume'],
            trade_data['price'],
            trade_data['stop_loss'],
            trade_data['take_profit']
        )
    
    async def calculate_only(self, user_id: int, signal_text: str) -> Dict[str, Any]:
        """Calculate trade metrics without executing"""
        try:
            # Manual previews use the same envelope normalization and parser as execution.
            from services.signal_pipeline import SignalPipeline
            envelope = SignalPipeline.normalize(UnifiedSignal(
                source='manual', payload=signal_text, user_id=user_id
            ))
            signal = self.signal_processor.process(envelope.payload, source=envelope.source)
            errors = signal.validate()
            if errors:
                raise TradeExecutionError('; '.join(errors))
            
            # Get user and account info
            user = self.user_repo.get_by_telegram_id(user_id)
            if not user:
                raise TradeExecutionError("User not found")
            
            # Get connection via ExecutionProvider
            connection = await self._get_connection(user_id)
            account_info = await connection.get_account_information()
            
            # Get current price if market order
            if signal.is_market_order and signal.entry is None:
                price = await connection.get_symbol_price(signal.symbol)
                if signal.order_type.value in ['Buy', 'Buy Limit', 'Buy Stop']:
                    signal.entry = float(price['ask'])
                else:
                    signal.entry = float(price['bid'])
            
            # Calculate risk only from authoritative broker metadata.
            get_constraints = getattr(connection, 'get_symbol_constraints', None)
            if get_constraints is None:
                return {
                    'success': False,
                    'error': 'Broker symbol constraints are unavailable; no executable sizing is shown.',
                    'status': 'constraints_unavailable',
                    'executable': False,
                }
            try:
                broker_constraints = await get_constraints(signal.symbol)
            except GatewayCapabilityUnavailable:
                return {
                    'success': False,
                    'error': 'Broker symbol constraints are unavailable; no executable sizing is shown.',
                    'status': 'constraints_unavailable',
                    'executable': False,
                }
            if not broker_constraints:
                return {
                    'success': False,
                    'error': 'Broker symbol constraints are unavailable; no executable sizing is shown.',
                    'status': 'constraints_unavailable',
                    'executable': False,
                }

            user_settings = {
                'default_risk_factor': user.default_risk_factor,
                'max_position_size': user.max_position_size,
                'symbol_risk_overrides': user.settings.symbol_risk_overrides if user.settings else {}
            }
            calculated = self.risk_service.calculate_trade(
                signal=signal,
                balance=account_info['balance'],
                risk_factor=user.default_risk_factor,
                user_settings=user_settings,
                broker_constraints=broker_constraints,
            )
            
            return {
                'success': True,
                'signal': {
                    'order_type': signal.order_type.value,
                    'symbol': signal.symbol,
                    'entry': signal.entry,
                    'stop_loss': signal.stop_loss,
                    'take_profits': signal.take_profits
                },
                'calculated': {
                    'position_size': calculated.position_size,
                    'stop_loss_pips': calculated.stop_loss_pips,
                    'take_profit_pips': calculated.take_profit_pips,
                    'risk_percentage': calculated.risk_percentage,
                    'potential_loss': calculated.potential_loss,
                    'potential_profits': calculated.potential_profits,
                    'total_profit': calculated.total_potential_profit,
                    'risk_reward': calculated.risk_reward_ratio
                },
                'account': {
                    'balance': account_info['balance'],
                    'currency': account_info.get('currency', 'USD')
                }
            }
            
        except Exception as e:
            logger.error("Calculation failed for user %s (%s)", user_id, type(e).__name__)
            return {
                'success': False,
                'error': 'Trade calculation failed'
            }
    
    async def close_trade(self, user_id: int, position_id: str) -> Dict[str, Any]:
        """Close an open position"""
        if getattr(settings, 'TRADING_DRY_RUN', True):
            logger.warning("Position close blocked by TRADING_DRY_RUN")
            return {'success': False, 'error': 'Trading is disabled in dry-run mode', 'status': 'dry_run'}
        try:
            # Get connection via ExecutionProvider — uses the adapter's close_position
            connection = await self._get_connection(user_id)
            success = await connection.close_position(position_id)
            
            if success:
                # Update trade record
                trade = self.db.query(Trade).filter(
                    Trade.user_id == user_id,
                    Trade.mt_order_ids.contains([position_id]),
                ).first()
                
                if trade:
                    trade.status = 'closed'
                    trade.closed_at = datetime.utcnow()
                    self.db.commit()
                
                return {
                    'success': True,
                    'message': f'Position {position_id} closed successfully'
                }
            else:
                return {
                    'success': False,
                    'error': 'Failed to close position'
                }
                
        except Exception as e:
            logger.error("Failed to close position for user %s (%s)", user_id, type(e).__name__)
            return {
                'success': False,
                'error': 'Position close failed'
            }
    
    async def modify_trade(self, user_id: int, position_id: str,
                          sl: Optional[float] = None, tp: Optional[float] = None) -> Dict[str, Any]:
        """Modify stop loss and take profit"""
        if getattr(settings, 'TRADING_DRY_RUN', True):
            logger.warning("Position modification blocked by TRADING_DRY_RUN")
            return {'success': False, 'error': 'Trading is disabled in dry-run mode', 'status': 'dry_run'}
        try:
            # Get connection via ExecutionProvider — uses the adapter's modify_position
            connection = await self._get_connection(user_id)
            success = await connection.modify_position(position_id, sl=sl, tp=tp)
            
            if success:
                return {
                    'success': True,
                    'message': f'Position {position_id} modified successfully'
                }
            else:
                return {
                    'success': False,
                    'error': 'Failed to modify position'
                }
                
        except Exception as e:
            logger.error("Failed to modify position for user %s (%s)", user_id, type(e).__name__)
            return {
                'success': False,
                'error': 'Position modification failed'
            }
    
    def get_pending_trades(self, user_id: int) -> List[Dict[str, Any]]:
        """Get list of pending/executed trades"""
        trades = self.trade_repo.get_user_trades(user_id, limit=20)
        
        return [{
            'id': t.uuid,
            'order_type': t.order_type,
            'symbol': t.symbol,
            'entry': float(t.entry_price),
            'size': float(t.position_size),
            'status': t.status,
            'created_at': t.created_at.isoformat(),
            'profit_loss': float(t.profit_loss) if t.profit_loss else None
        } for t in trades]
    
    def _get_recent_signals(self, user_id: int, minutes: int = 5) -> List[TradeSignal]:
        """Get recent signals for duplicate detection"""
        from datetime import timedelta
        
        cutoff = datetime.utcnow() - timedelta(minutes=minutes)
        recent_trades = self.db.query(Trade).filter(
            Trade.user_id == self.user_repo.get_by_telegram_id(user_id).id,
            Trade.created_at >= cutoff
        ).all()
        
        signals = []
        for trade in recent_trades:
            try:
                signal = TradeSignal(
                    order_type=trade.order_type,
                    symbol=trade.symbol,
                    entry=float(trade.entry_price),
                    stop_loss=float(trade.stop_loss),
                    take_profits=[float(tp) for tp in trade.take_profits]
                )
                signals.append(signal)
            except:
                continue
        
        return signals
