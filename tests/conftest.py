"""Keep unit tests independent of deployment-only environment configuration."""
import sys
import types


# Importing any ``config`` submodule eagerly constructs Settings and demands
# production credentials. Supply only the stable configuration values used by
# the pure parsing/risk code in this test process.
if "config.settings" not in sys.modules:
    module = types.ModuleType("config.settings")

    class _TestSettings:
        ALLOWED_SYMBOLS = [
            "AUDCAD", "AUDCHF", "AUDJPY", "AUDNZD", "AUDUSD", "CADCHF",
            "CADJPY", "CHFJPY", "EURAUD", "EURCAD", "EURCHF", "EURGBP",
            "EURJPY", "EURNZD", "EURUSD", "GBPAUD", "GBPCAD", "GBPCHF",
            "GBPJPY", "GBPNZD", "GBPUSD", "NZDCAD", "NZDCHF", "NZDJPY",
            "NZDUSD", "USDCAD", "USDCHF", "USDJPY", "XAGUSD", "XAUUSD",
        ]
        DEFAULT_RISK_FACTOR = 0.01
        MAX_RISK_FACTOR = 0.05
        MIN_RISK_FACTOR = 0.001
        DEFAULT_MAX_POSITION_SIZE = 10.0

    module.settings = _TestSettings()
    sys.modules["config.settings"] = module
