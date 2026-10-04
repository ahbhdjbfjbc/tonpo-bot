"""Services package for business logic.

Exports are loaded on demand so importing a focused service does not require
every optional integration (for example Redis) to be installed and configured.
"""

from importlib import import_module

__all__ = [
    'AuthService',
    'EncryptionService',
    'SignalProcessor',
    'SignalValidator',
    'NotificationService',
    'SubscriptionService',
    'RiskService',
    'TradeExecutor',
    'SignalPipeline',
    'AnalyticsService',
    'CacheService',
    'QueueService',
    'MonitoringService'
]

_EXPORTS = {
    'AuthService': '.auth', 'EncryptionService': '.auth',
    'SignalProcessor': '.signal_processor', 'SignalValidator': '.signal_processor',
    'NotificationService': '.notification', 'SubscriptionService': '.subscription',
    'RiskService': '.risk_service', 'TradeExecutor': '.trade_executor',
    'SignalPipeline': '.signal_pipeline',
    'AnalyticsService': '.analytics', 'CacheService': '.cache',
    'QueueService': '.queue', 'MonitoringService': '.monitoring',
}


def __getattr__(name):
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name, __name__), name)
    globals()[name] = value
    return value
