# fx/services/risk_service.py
"""
Risk management service
Calculates position sizes and risk metrics
"""
import math
from typing import Dict, Any, List, Optional, Tuple
from decimal import Decimal
import logging

from core.models import TradeSignal, CalculatedTrade
from config.constants import PIP_MULTIPLIERS, JPY_SYMBOLS

logger = logging.getLogger(__name__)


class RiskService:
    """
    Handles all risk calculations for trades
    """
    
    def __init__(self):
        self.default_risk_factor = 0.01  # 1%
        self.max_risk_factor = 0.05  # 5%
        self.min_risk_factor = 0.001  # 0.1%
    
    def calculate_position_size(self, balance: float, stop_loss_pips: int,
                                risk_factor: float, symbol: str) -> float:
        """
        Calculate position size based on risk
        
        Formula: (Balance * Risk%) / (Stop Loss in Pips * Pip Value)
        Pip Value for 1 standard lot = $10 per pip
        """
        if stop_loss_pips <= 0:
            raise ValueError("Stop loss must be positive")
        
        # Standard lot pip value is $10
        pip_value = 10.0
        
        # Adjust for different symbols if needed
        if symbol in ['XAUUSD', 'XAGUSD']:
            pip_value = 1.0  # Different pip value for metals
        
        # Calculate raw position size in lots
        raw_size = (balance * risk_factor) / (stop_loss_pips * pip_value)
        
        # Round to 2 decimal places (standard lot increments)
        position_size = math.floor(raw_size * 100) / 100
        
        return position_size
    
    def calculate_pips(self, price1: float, price2: float, symbol: str) -> int:
        """Calculate the difference in pips between two prices"""
        multiplier = self._get_pip_multiplier(symbol)
        return abs(round((price1 - price2) / multiplier))
    
    def _get_pip_multiplier(self, symbol: str) -> float:
        """Get pip multiplier for symbol"""
        if symbol == 'XAUUSD':
            return 0.1
        elif symbol == 'XAGUSD':
            return 0.001
        elif any(jpy in symbol for jpy in JPY_SYMBOLS):
            return 0.01
        else:
            return 0.0001
    
    def calculate_risk_reward(self, entry: float, stop_loss: float, 
                             take_profits: List[float]) -> Dict[str, float]:
        """Calculate risk/reward ratio"""
        risk = abs(entry - stop_loss)
        if risk == 0:
            return {'ratio': 0, 'risk': 0, 'avg_reward': 0}
        
        # For multiple TPs, calculate average reward
        if len(take_profits) > 1:
            total_reward = sum(abs(tp - entry) for tp in take_profits)
            avg_reward = total_reward / len(take_profits)
            ratio = avg_reward / risk
        else:
            reward = abs(take_profits[0] - entry)
            ratio = reward / risk
            avg_reward = reward
        
        return {
            'ratio': ratio,
            'risk': risk,
            'avg_reward': avg_reward,
            'risk_usd': None,  # Will be filled with actual USD values
            'reward_usd': None
        }
    
    def calculate_monetary_risk(self, position_size: float, stop_loss_pips: int,
                               symbol: str) -> float:
        """Calculate monetary risk in account currency"""
        pip_value = 10.0 * position_size  # $10 per pip per standard lot
        return pip_value * stop_loss_pips
    
    def calculate_potential_profit(self, position_size: float, take_profit_pips: List[int],
                                  split_position: bool = True) -> List[float]:
        """Calculate potential profit for each TP"""
        profits = []
        
        if split_position and len(take_profit_pips) > 1:
            size_per_tp = position_size / len(take_profit_pips)
            for pips in take_profit_pips:
                profit = (size_per_tp * 10) * pips
                profits.append(round(profit, 2))
        else:
            for pips in take_profit_pips:
                profit = (position_size * 10) * pips
                profits.append(round(profit, 2))
        
        return profits
    
    @staticmethod
    def validate_broker_constraints(broker_constraints: Dict[str, float]) -> Dict[str, float]:
        """Validate only authoritative broker metadata; never supply defaults."""
        required = ('tick_size', 'tick_value', 'volume_step', 'volume_min', 'volume_max')
        if not isinstance(broker_constraints, dict) or any(
            key not in broker_constraints for key in required
        ):
            raise ValueError('Broker symbol constraints are incomplete')
        values = {}
        for key in required:
            try:
                value = float(broker_constraints[key])
            except (TypeError, ValueError) as exc:
                raise ValueError('Broker symbol constraints are malformed') from exc
            if not math.isfinite(value) or value <= 0:
                raise ValueError('Broker symbol constraints are invalid')
            values[key] = value
        if values['volume_min'] > values['volume_max']:
            raise ValueError('Broker volume bounds are invalid')
        if values['volume_step'] > values['volume_max']:
            raise ValueError('Broker volume step is invalid')
        return values

    def calculate_trade(self, signal: TradeSignal, balance: float,
                       risk_factor: Optional[float] = None,
                       user_settings: Optional[Dict[str, Any]] = None,
                       broker_constraints: Optional[Dict[str, float]] = None) -> CalculatedTrade:
        """
        Calculate all trade metrics. Broker constraints are mandatory for
        executable sizing and are validated without fabricated defaults.
        """
        if not math.isfinite(float(balance)) or balance <= 0:
            raise ValueError('Account balance must be a finite positive number')
        if signal.entry is None or not math.isfinite(float(signal.entry)) or signal.entry <= 0:
            raise ValueError('A valid entry price is required for risk calculation')

        # Use explicit zero as invalid input instead of silently replacing it
        # with the default and increasing the requested exposure.
        risk = self.default_risk_factor if risk_factor is None else float(risk_factor)
        
        # Check if there's a symbol-specific override
        if user_settings and 'symbol_risk_overrides' in user_settings:
            overrides = user_settings['symbol_risk_overrides']
            if signal.symbol in overrides:
                risk = float(overrides[signal.symbol])
                logger.info(f"Using symbol override for {signal.symbol}: {risk}")

        if not math.isfinite(risk) or risk <= 0:
            raise ValueError('Risk factor must be a finite positive number')
        
        # Validate risk
        configured_max = self.max_risk_factor
        configured_min = self.min_risk_factor
        if user_settings:
            configured_max = float(user_settings.get('max_risk_per_trade', configured_max))
            configured_min = float(user_settings.get('min_risk_per_trade', configured_min))
        if not math.isfinite(configured_max) or not math.isfinite(configured_min) or configured_max <= 0 or configured_min <= 0:
            raise ValueError('Risk limits must be finite and positive')
        if risk > configured_max:
            logger.warning(f"Risk {risk} exceeds maximum, capping at {configured_max}")
            risk = configured_max
        elif risk < configured_min:
            raise ValueError('Risk factor is below the configured minimum')
        
        # Calculate stop loss in pips
        stop_loss_pips = self.calculate_pips(signal.entry, signal.stop_loss, signal.symbol)
        
        # Calculate position size
        position_size = self.calculate_position_size(balance, stop_loss_pips, risk, signal.symbol)
        
        # Apply max position size limit
        if user_settings and 'max_position_size' in user_settings:
            max_size = user_settings['max_position_size']
            if position_size > max_size:
                logger.info(f"Position size {position_size} capped at {max_size}")
                position_size = max_size
        
        # Calculate take profits in pips
        take_profit_pips = []
        for tp in signal.take_profits:
            pips = self.calculate_pips(tp, signal.entry, signal.symbol)
            take_profit_pips.append(pips)
        
        # Calculate monetary values
        potential_loss = self.calculate_monetary_risk(position_size, stop_loss_pips, signal.symbol)
        potential_profits = self.calculate_potential_profit(
            position_size, take_profit_pips, 
            split_position=len(signal.take_profits) > 1
        )
        
        # Calculate risk/reward
        rr_info = self.calculate_risk_reward(signal.entry, signal.stop_loss, signal.take_profits)
        
        if broker_constraints is not None:
            broker_constraints = self.validate_broker_constraints(broker_constraints)
            tick_size = broker_constraints['tick_size']
            tick_value = broker_constraints['tick_value']
            volume_step = broker_constraints['volume_step']
            volume_min = broker_constraints['volume_min']
            volume_max = broker_constraints['volume_max']
            if user_settings and user_settings.get('max_position_size'):
                volume_max = min(volume_max, float(user_settings['max_position_size']))
            if (not all(math.isfinite(value) for value in
                        (tick_size, tick_value, volume_step, volume_min, volume_max))
                    or min(tick_size, tick_value, volume_step, volume_min, volume_max) <= 0):
                raise ValueError('Broker returned invalid symbol constraints')
            risk_per_lot = abs(signal.entry - signal.stop_loss) / tick_size * tick_value
            if risk_per_lot <= 0:
                raise ValueError('Broker risk per lot must be positive')
            risk_budget = balance * risk
            raw_size = min(risk_budget / risk_per_lot, volume_max)
            position_size = math.floor(raw_size / volume_step + 1e-9) * volume_step
            decimals = max(0, -Decimal(str(volume_step)).normalize().as_tuple().exponent)
            position_size = round(position_size, decimals)
            if position_size < volume_min:
                raise ValueError('Risk budget is below broker minimum volume')
            potential_loss = risk_per_lot * position_size
            per_tp_volume = position_size / len(signal.take_profits)
            potential_profits = [abs(tp - signal.entry) / tick_size * tick_value * per_tp_volume
                                 for tp in signal.take_profits]
            risk = potential_loss / balance

        return CalculatedTrade(
            signal=signal,
            balance=balance,
            position_size=position_size,
            stop_loss_pips=stop_loss_pips,
            take_profit_pips=take_profit_pips,
            potential_loss=potential_loss,
            potential_profits=potential_profits,
            risk_percentage=risk * 100,
            risk_reward_ratio=rr_info['ratio']
        )
    
    def validate_trade_parameters(self, signal: TradeSignal, balance: float,
                                 user_settings: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """
        Validate if trade parameters are within acceptable limits
        """
        errors = []
        
        # Check balance
        if balance <= 0:
            errors.append("Insufficient balance")
        
        # Check stop loss distance
        sl_pips = self.calculate_pips(signal.entry, signal.stop_loss, signal.symbol)
        min_sl = user_settings.get('min_stop_loss_pips', 10)
        if sl_pips < min_sl:
            errors.append(f"Stop loss too tight: {sl_pips} < {min_sl} pips")
        
        max_sl = user_settings.get('max_stop_loss_pips', 500)
        if sl_pips > max_sl:
            errors.append(f"Stop loss too wide: {sl_pips} > {max_sl} pips")
        
        # Check take profit distances
        for i, tp in enumerate(signal.take_profits):
            tp_pips = self.calculate_pips(tp, signal.entry, signal.symbol)
            min_tp = user_settings.get('min_take_profit_pips', 10)
            if tp_pips < min_tp:
                errors.append(f"TP{i+1} too tight: {tp_pips} < {min_tp} pips")
        
        # Check risk/reward ratio
        rr = self.calculate_risk_reward(signal.entry, signal.stop_loss, signal.take_profits)
        min_rr = user_settings.get('min_risk_reward', 1.0)
        if rr['ratio'] < min_rr:
            errors.append(f"Risk/reward too low: {rr['ratio']:.2f} < {min_rr}")
        
        # Check position size against max
        if user_settings.get('max_position_size'):
            sl_pips = self.calculate_pips(signal.entry, signal.stop_loss, signal.symbol)
            risk = user_settings.get('default_risk_factor', self.default_risk_factor)
            position_size = self.calculate_position_size(balance, sl_pips, risk, signal.symbol)
            
            if position_size > user_settings['max_position_size']:
                errors.append(f"Position size would exceed maximum: {position_size:.2f}")
        
        return len(errors) == 0, errors
    
    def suggest_risk_adjustment(self, signal: TradeSignal, balance: float,
                               user_settings: Dict[str, Any]) -> Dict[str, Any]:
        """
        Suggest risk adjustment to meet user's constraints
        """
        suggestions = {}
        
        # Calculate current metrics
        sl_pips = self.calculate_pips(signal.entry, signal.stop_loss, signal.symbol)
        current_risk = user_settings.get('default_risk_factor', self.default_risk_factor)
        current_size = self.calculate_position_size(balance, sl_pips, current_risk, signal.symbol)
        
        # Check against max position size
        max_size = user_settings.get('max_position_size', float('inf'))
        if current_size > max_size:
            # Calculate risk factor that would achieve max size
            suggested_risk = (max_size * sl_pips * 10) / balance
            suggestions['risk_factor'] = round(suggested_risk, 4)
            suggestions['position_size'] = max_size
            suggestions['message'] = f"Reduce risk to {suggested_risk:.2%} to meet max position size"
        
        # Check min risk/reward
        min_rr = user_settings.get('min_risk_reward', 1.0)
        rr = self.calculate_risk_reward(signal.entry, signal.stop_loss, signal.take_profits)
        if rr['ratio'] < min_rr:
            suggestions['rr_ratio'] = rr['ratio']
            suggestions['message'] = f"Risk/reward {rr['ratio']:.2f} below minimum {min_rr}"
        
        return suggestions
