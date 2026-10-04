# fx/services/signal_processor.py
import re
import hashlib
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime
import logging

from core.models import TradeSignal
from config.constants import OrderType, PIP_MULTIPLIERS, JPY_SYMBOLS
from config.settings import settings
from core.parser import SignalParser

logger = logging.getLogger(__name__)


class SignalValidationError(Exception):
    """Raised when signal validation fails"""
    pass


class SignalValidator:
    """
    Validates trading signals against user settings and market conditions
    """
    
    def __init__(self, user_settings: Optional[Dict[str, Any]] = None):
        self.user_settings = user_settings or {}
        self.allowed_symbols = self.user_settings.get('allowed_symbols', settings.ALLOWED_SYMBOLS)
        self.blocked_symbols = self.user_settings.get('blocked_symbols', [])
    
    def validate_symbol(self, symbol: str) -> Tuple[bool, str]:
        """Validate if symbol is allowed"""
        if symbol not in self.allowed_symbols:
            return False, f"Symbol {symbol} not in allowed list"
        
        if symbol in self.blocked_symbols:
            return False, f"Symbol {symbol} is blocked"
        
        return True, "Symbol valid"
    
    def validate_risk(self, risk_percentage: float) -> Tuple[bool, str]:
        """Validate risk percentage"""
        max_risk = self.user_settings.get('max_risk_per_trade', 0.05)  # 5% max
        min_risk = self.user_settings.get('min_risk_per_trade', 0.001)  # 0.1% min
        
        if risk_percentage > max_risk:
            return False, f"Risk {risk_percentage:.2%} exceeds maximum {max_risk:.2%}"
        
        if risk_percentage < min_risk:
            return False, f"Risk {risk_percentage:.2%} below minimum {min_risk:.2%}"
        
        return True, "Risk valid"
    
    def validate_price_distance(self, entry: float, current_price: float, 
                               symbol: str) -> Tuple[bool, str]:
        """Validate distance from current price"""
        min_distance = self.user_settings.get('min_distance_from_price', 0)
        if min_distance == 0:
            return True, "Distance check disabled"
        
        # Calculate pip distance
        multiplier = self._get_pip_multiplier(symbol)
        distance_pips = abs(entry - current_price) / multiplier
        
        if distance_pips < min_distance:
            return False, f"Entry too close to market price ({distance_pips:.0f} < {min_distance} pips)"
        
        return True, "Distance valid"
    
    def validate_spread(self, symbol: str, bid: float, ask: float) -> Tuple[bool, str]:
        """Validate spread is within limits"""
        max_spread = self.user_settings.get('max_spread')
        if not max_spread:
            return True, "Spread check disabled"
        
        spread = abs(ask - bid)
        if spread > max_spread:
            return False, f"Spread {spread:.5f} exceeds maximum {max_spread:.5f}"
        
        return True, "Spread valid"
    
    def _get_pip_multiplier(self, symbol: str) -> float:
        """Get pip multiplier for symbol"""
        if symbol == 'XAUUSD':
            return PIP_MULTIPLIERS['XAUUSD']
        elif symbol == 'XAGUSD':
            return PIP_MULTIPLIERS['XAGUSD']   # 0.001
        elif any(jpy in symbol for jpy in JPY_SYMBOLS):
            return 0.01
        else:
            return PIP_MULTIPLIERS['forex']


class SignalProcessor:
    """Compatibility facade over the canonical core SignalParser."""

    def __init__(self):
        self.parser = SignalParser()

    def process(self, text: str, source: str = 'telegram') -> TradeSignal:
        if not text or not text.strip():
            raise SignalValidationError("Could not parse an empty signal")
        normalized_text = text.strip()
        try:
            signal = self.parser.parse(normalized_text, source=source)
        except Exception as exc:
            raise SignalValidationError("Could not parse signal with the canonical parser") from exc
        signal.metadata.update({
            'source': source,
            'received_at': datetime.utcnow(),
            'raw_text': normalized_text,
            'hash': self._calculate_hash(normalized_text),
        })
        return signal

    def _calculate_hash(self, text: str) -> str:
        normalized = ' '.join(text.lower().split())
        return hashlib.sha256(normalized.encode()).hexdigest()

    def extract_symbols(self, text: str) -> List[str]:
        words = re.findall(r'\b[A-Z]{6}\b', text.upper())
        return [word for word in words if word in settings.ALLOWED_SYMBOLS]

    def is_duplicate(self, signal: TradeSignal, recent_signals: List[TradeSignal]) -> bool:
        for recent in recent_signals:
            recent_order_type = getattr(recent.order_type, 'value', recent.order_type)
            signal_order_type = getattr(signal.order_type, 'value', signal.order_type)
            if (recent.symbol == signal.symbol and recent_order_type == signal_order_type
                    and abs(recent.stop_loss - signal.stop_loss) < 0.0001):
                return True
        return False


class SignalEnricher:
    """
    Enriches signals with additional data
    """
    
    def __init__(self):
        pass
    
    def add_pip_values(self, signal: TradeSignal) -> Dict[str, Any]:
        """Add pip values to signal"""
        # Determine pip multiplier
        if signal.symbol == 'XAUUSD':
            multiplier = 0.1
        elif signal.symbol == 'XAGUSD':
            multiplier = 0.001
        elif 'JPY' in signal.symbol:
            multiplier = 0.01
        else:
            multiplier = 0.0001
        
        # Calculate SL in pips
        if signal.entry:
            sl_pips = abs(signal.stop_loss - signal.entry) / multiplier
        else:
            sl_pips = None
        
        # Calculate TPs in pips
        tp_pips = []
        if signal.entry:
            for tp in signal.take_profits:
                tp_pips.append(abs(tp - signal.entry) / multiplier)
        
        return {
            'sl_pips': sl_pips,
            'tp_pips': tp_pips,
            'pip_multiplier': multiplier
        }
    
    def estimate_risk_reward(self, signal: TradeSignal) -> Dict[str, float]:
        """Estimate risk/reward ratio"""
        if not signal.entry:
            return {'rr_ratio': None}
        
        risk = abs(signal.entry - signal.stop_loss)
        if risk == 0:
            return {'rr_ratio': 0}
        
        # Average reward (for multiple TPs)
        avg_reward = sum(abs(tp - signal.entry) for tp in signal.take_profits) / len(signal.take_profits)
        
        return {
            'rr_ratio': avg_reward / risk,
            'risk': risk,
            'avg_reward': avg_reward
        }
