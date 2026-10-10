# fx/config/settings.py
import os
import json
from typing import List, Optional, Dict, Any
from urllib.parse import urlsplit
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator, model_validator, Field
from cryptography.fernet import Fernet
from dotenv import load_dotenv
from config.webhook import require_webhook_url, validate_webhook_url

# Load environment variables from .env file
load_dotenv()

class Settings(BaseSettings):
    """
    Application settings with validation
    """
    model_config = SettingsConfigDict(
        env_file='.env',
        env_file_encoding='utf-8',
        case_sensitive=True,
        extra='ignore'
    )
    
    # App Info
    APP_NAME: str = "Tonpo Bot"
    APP_VERSION: str = "1.0.0"
    APP_DESCRIPTION: str = "Telegram Bot for MetaTrader 5 Trading"
    DEBUG: bool = Field(False, validation_alias='DEBUG')
    
    # Gateway settings
    GATEWAY_HOST: str = Field(
        default="localhost",
        validation_alias="GATEWAY_HOST"
    )
    GATEWAY_PORT: int = Field(
        default=8080,
        validation_alias="GATEWAY_PORT",
        ge=1,
        le=65535
    )
    GATEWAY_USE_SSL: bool = Field(
        default=False,
        validation_alias="GATEWAY_USE_SSL"
    )
    GATEWAY_API_KEY_HEADER: str = Field(
        default="X-API-Key",
        validation_alias="GATEWAY_API_KEY_HEADER"
    )
    GATEWAY_CONNECT_TIMEOUT: float = Field(
        default=10.0,
        validation_alias="GATEWAY_CONNECT_TIMEOUT",
        gt=0
    )
    GATEWAY_REQUEST_TIMEOUT: float = Field(
        default=30.0,
        validation_alias="GATEWAY_REQUEST_TIMEOUT",
        gt=0
    )
    ENGINE_PROVIDER: str = Field('tonpo', validation_alias='ENGINE_PROVIDER')
    METADOCKER_REQUEST_TIMEOUT: float = Field(15.0, validation_alias='METADOCKER_REQUEST_TIMEOUT', gt=0, le=120)
    METADOCKER_MAX_TICK_AGE_SECONDS: float = Field(10.0, validation_alias='METADOCKER_MAX_TICK_AGE_SECONDS', gt=0, le=300)
    METADOCKER_ALLOWED_HOSTS: str = Field('', validation_alias='METADOCKER_ALLOWED_HOSTS')
    METADOCKER_REQUIRE_HTTPS: bool = Field(True, validation_alias='METADOCKER_REQUIRE_HTTPS')
    
    @property
    def gateway_config(self):
        """Get the Tonpo SDK configuration for the configured gateway."""
        from tonpo import TonpoConfig
        return TonpoConfig(
            host=self.GATEWAY_HOST,
            port=self.GATEWAY_PORT,
            use_ssl=self.GATEWAY_USE_SSL,
            api_key_header=self.GATEWAY_API_KEY_HEADER,
            connect_timeout=self.GATEWAY_CONNECT_TIMEOUT,
            request_timeout=self.GATEWAY_REQUEST_TIMEOUT,
        )
        
    # Telegram Configuration
    BOT_TOKEN: str = Field(..., validation_alias='BOT_TOKEN')
    BOT_USERNAME: Optional[str] = Field(None, validation_alias='BOT_USERNAME')
    WEB_APP_URL: Optional[str] = Field(None, validation_alias='WEB_APP_URL')
    TELEGRAM_WEBAPP_INIT_DATA_MAX_AGE_SECONDS: int = Field(
        86400, validation_alias='TELEGRAM_WEBAPP_INIT_DATA_MAX_AGE_SECONDS',
        gt=0, le=86400,
    )
    TELEGRAM_CONNECT_TIMEOUT: float = Field(15.0, validation_alias='TELEGRAM_CONNECT_TIMEOUT', gt=0, le=120)
    TELEGRAM_READ_TIMEOUT: float = Field(15.0, validation_alias='TELEGRAM_READ_TIMEOUT', gt=0, le=120)
    TELEGRAM_WRITE_TIMEOUT: float = Field(15.0, validation_alias='TELEGRAM_WRITE_TIMEOUT', gt=0, le=120)
    TELEGRAM_POOL_TIMEOUT: float = Field(5.0, validation_alias='TELEGRAM_POOL_TIMEOUT', gt=0, le=60)
    REGISTRATION_PASSWORD_TTL_SECONDS: int = Field(
        300, validation_alias='REGISTRATION_PASSWORD_TTL_SECONDS', gt=0, le=3600
    )
    TELEGRAM_PROXY: Optional[str] = Field(None, validation_alias='TELEGRAM_PROXY')
    ADMIN_USER_IDS: List[int] = Field(default=[], validation_alias='ADMIN_USER_IDS')
    USE_WEBHOOK: bool = Field(False, validation_alias='USE_WEBHOOK')
    WEBHOOK_URL: Optional[str] = Field(None, validation_alias='WEBHOOK_URL')
    WEBHOOK_PORT: int = Field(8443, validation_alias='WEBHOOK_PORT', ge=1, le=65535)
    WEBHOOK_HOST: str = Field("0.0.0.0", validation_alias='WEBHOOK_HOST')
    
    @field_validator('BOT_TOKEN')
    @classmethod
    def validate_bot_token(cls, v: str) -> str:
        if not v or ':' not in v:
            raise ValueError("Invalid BOT_TOKEN format")
        return v

    @field_validator('WEB_APP_URL')
    @classmethod
    def validate_web_app_url(cls, v: Optional[str]) -> Optional[str]:
        if not v:
            return v
        parsed = urlsplit(v)
        if parsed.scheme != 'https' or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError('WEB_APP_URL must be an HTTPS URL without embedded credentials')
        return v.rstrip('/')

    @field_validator('WEBHOOK_URL')
    @classmethod
    def validate_webhook_url(cls, v: Optional[str]) -> Optional[str]:
        return validate_webhook_url(v)

    @model_validator(mode='after')
    def require_webhook_url_when_enabled(self):
        require_webhook_url(self.USE_WEBHOOK, self.WEBHOOK_URL)
        return self
    
    @field_validator('ADMIN_USER_IDS', mode='before')
    @classmethod
    def parse_admin_ids(cls, v):
        """Parse admin IDs from environment variable"""
        if v is None:
            return []
        if isinstance(v, str):
            # Strip inline comments before any parsing
            v = v.split('#')[0].strip()
            if not v:
            	return []
            # Try to parse as JSON first
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                # Fall back to comma-separated parsing
                return [int(id.strip()) for id in v.split(',') if id.strip()]
        if isinstance(v, (list, tuple)):
            return [int(id) for id in v]
        return v
    
    # Database Configuration
    DATABASE_URL: str = Field(..., validation_alias='DATABASE_URL')
    DATABASE_POOL_SIZE: int = Field(20, validation_alias='DATABASE_POOL_SIZE')
    DATABASE_MAX_OVERFLOW: int = Field(10, validation_alias='DATABASE_MAX_OVERFLOW')
    DATABASE_POOL_TIMEOUT: int = Field(30, validation_alias='DATABASE_POOL_TIMEOUT')
    DATABASE_ECHO: bool = Field(False, validation_alias='DATABASE_ECHO')
    
    @field_validator('DATABASE_URL')
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        if not v:
            raise ValueError("DATABASE_URL must be set")
        # Handle Heroku's postgres:// vs postgresql://
        if v.startswith("postgres://"):
            v = v.replace("postgres://", "postgresql://", 1)
        if v.startswith("postgresql://"):
            v = v.replace("postgresql://", "postgresql+psycopg2://", 1)
        return v
    
    # Redis Configuration
    REDIS_URL: Optional[str] = Field(None, validation_alias='REDIS_URL')
    REDIS_MAX_CONNECTIONS: int = Field(10, validation_alias='REDIS_MAX_CONNECTIONS')
    REDIS_SOCKET_TIMEOUT: int = Field(5, validation_alias='REDIS_SOCKET_TIMEOUT')
    
    # Security
    ENCRYPTION_KEY: str = Field(..., validation_alias='ENCRYPTION_KEY')
    JWT_SECRET: str = Field(..., validation_alias='JWT_SECRET')
    ADMIN_API_KEY: Optional[str] = Field(None, validation_alias='ADMIN_API_KEY')
    JWT_ALGORITHM: str = Field("HS256", validation_alias='JWT_ALGORITHM')
    JWT_EXPIRY_HOURS: int = Field(24, validation_alias='JWT_EXPIRY_HOURS')
    CORS_ORIGINS: List[str] = Field(
        default_factory=lambda: [
            'http://localhost:3000', 'http://127.0.0.1:3000',
            'http://localhost:5173', 'http://127.0.0.1:5173',
        ],
        validation_alias='CORS_ORIGINS',
    )

    # Economic calendar protection is enabled by default. Missing/unavailable
    # data blocks new trades until a real provider is provisioned.
    NEWS_PROTECTION_ENABLED: bool = Field(True, validation_alias='NEWS_PROTECTION_ENABLED')
    NEWS_PROVIDER_URL: Optional[str] = Field(None, validation_alias='NEWS_PROVIDER_URL')
    NEWS_PROVIDER_TIMEOUT_SECONDS: float = Field(5.0, validation_alias='NEWS_PROVIDER_TIMEOUT_SECONDS', gt=0, le=30)
    TRADING_ECONOMICS_API_KEY: Optional[str] = Field(None, validation_alias='TRADING_ECONOMICS_API_KEY', repr=False)
    TRADING_ECONOMICS_BASE_URL: str = Field('https://api.tradingeconomics.com', validation_alias='TRADING_ECONOMICS_BASE_URL')
    TRADING_ECONOMICS_TIMEOUT_SECONDS: float = Field(5.0, validation_alias='TRADING_ECONOMICS_TIMEOUT_SECONDS', gt=0, le=30)
    TRADING_ECONOMICS_CACHE_SECONDS: int = Field(60, validation_alias='TRADING_ECONOMICS_CACHE_SECONDS', ge=0, le=3600)
    TRADING_ECONOMICS_STALE_AFTER_SECONDS: int = Field(300, validation_alias='TRADING_ECONOMICS_STALE_AFTER_SECONDS', gt=0, le=86400)
    NEWS_PRE_WINDOW_MINUTES: int = Field(30, validation_alias='NEWS_PRE_WINDOW_MINUTES', ge=0, le=1440)
    NEWS_POST_WINDOW_MINUTES: int = Field(30, validation_alias='NEWS_POST_WINDOW_MINUTES', ge=0, le=1440)

    @field_validator('JWT_SECRET')
    @classmethod
    def validate_jwt_secret(cls, value: str) -> str:
        if len(value) < 32:
            raise ValueError('JWT_SECRET must be at least 32 characters')
        return value

    @field_validator('CORS_ORIGINS')
    @classmethod
    def validate_cors_origins(cls, origins: List[str]) -> List[str]:
        validated = []
        for origin in origins:
            value = origin.strip().rstrip('/')
            parsed = urlsplit(value)
            if (value == '*' or parsed.scheme not in {'http', 'https'}
                    or not parsed.netloc or parsed.username or parsed.password
                    or parsed.path or parsed.query or parsed.fragment):
                raise ValueError('CORS_ORIGINS must contain explicit HTTP(S) origins without paths or credentials')
            validated.append(value)
        return validated

    @field_validator('ENCRYPTION_KEY')
    @classmethod
    def validate_encryption_key(cls, value: str) -> str:
        try:
            Fernet(value.encode('ascii'))
        except (AttributeError, UnicodeEncodeError, ValueError, TypeError) as exc:
            raise ValueError('ENCRYPTION_KEY must be a valid Fernet key') from exc
        return value
    
    # Trading Configuration
    DEFAULT_RISK_FACTOR: float = Field(0.01, validation_alias='DEFAULT_RISK_FACTOR')
    MAX_RISK_FACTOR: float = Field(0.05, validation_alias='MAX_RISK_FACTOR')
    MIN_RISK_FACTOR: float = Field(0.001, validation_alias='MIN_RISK_FACTOR')
    DEFAULT_MAX_POSITION_SIZE: float = Field(10.0, validation_alias='DEFAULT_MAX_POSITION_SIZE')
    ALLOWED_SYMBOLS: List[str] = Field([
        'AUDCAD', 'AUDCHF', 'AUDJPY', 'AUDNZD', 'AUDUSD',
        'CADCHF', 'CADJPY', 'CHFJPY', 'EURAUD', 'EURCAD',
        'EURCHF', 'EURGBP', 'EURJPY', 'EURNZD', 'EURUSD',
        'GBPAUD', 'GBPCAD', 'GBPCHF', 'GBPJPY', 'GBPNZD',
        'GBPUSD', 'NZDCAD', 'NZDCHF', 'NZDJPY', 'NZDUSD',
        'USDCAD', 'USDCHF', 'USDJPY', 'XAGUSD', 'XAUUSD'
    ], validation_alias='ALLOWED_SYMBOLS')
    
    @field_validator('ALLOWED_SYMBOLS', mode='before')
    @classmethod
    def parse_symbols(cls, v):
        """Parse symbols from environment variable"""
        if v is None:
            return []
        if isinstance(v, str):
            # Try to parse as JSON first
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                # Fall back to comma-separated parsing
                return [s.strip().upper() for s in v.split(',') if s.strip()]
        if isinstance(v, (list, tuple)):
            return [str(s).upper() for s in v]
        return v
    
    # Rate Limiting
    RATE_LIMIT_TRADES: int = Field(5, validation_alias='RATE_LIMIT_TRADES')
    RATE_LIMIT_CALCULATIONS: int = Field(10, validation_alias='RATE_LIMIT_CALCULATIONS')
    RATE_LIMIT_BALANCE: int = Field(30, validation_alias='RATE_LIMIT_BALANCE')
    RATE_LIMIT_POSITIONS: int = Field(20, validation_alias='RATE_LIMIT_POSITIONS')
    RATE_LIMIT_SETTINGS: int = Field(20, validation_alias='RATE_LIMIT_SETTINGS')
    RATE_LIMIT_DEFAULT: int = Field(30, validation_alias='RATE_LIMIT_DEFAULT')
    
    # Subscription Plans (prices in USD)
    FREE_PLAN_MAX_TRADES: int = Field(10, validation_alias='FREE_PLAN_MAX_TRADES')
    FREE_PLAN_MAX_SIZE: float = Field(1.0, validation_alias='FREE_PLAN_MAX_SIZE')
    
    BASIC_PLAN_PRICE: float = Field(9.99, validation_alias='BASIC_PLAN_PRICE')
    BASIC_PLAN_MAX_TRADES: int = Field(50, validation_alias='BASIC_PLAN_MAX_TRADES')
    BASIC_PLAN_MAX_SIZE: float = Field(5.0, validation_alias='BASIC_PLAN_MAX_SIZE')
    
    PRO_PLAN_PRICE: float = Field(29.99, validation_alias='PRO_PLAN_PRICE')
    PRO_PLAN_MAX_TRADES: int = Field(200, validation_alias='PRO_PLAN_MAX_TRADES')
    PRO_PLAN_MAX_SIZE: float = Field(10.0, validation_alias='PRO_PLAN_MAX_SIZE')
    
    ENTERPRISE_PLAN_PRICE: float = Field(99.99, validation_alias='ENTERPRISE_PLAN_PRICE')
    ENTERPRISE_PLAN_MAX_TRADES: int = Field(1000, validation_alias='ENTERPRISE_PLAN_MAX_TRADES')
    ENTERPRISE_PLAN_MAX_SIZE: float = Field(50.0, validation_alias='ENTERPRISE_PLAN_MAX_SIZE')

    # Payment request configuration. A request is never treated as paid until
    # an external verifier confirms it; missing wallets fail closed.
    USDT_WALLET_ADDRESS: Optional[str] = Field(None, validation_alias='USDT_WALLET_ADDRESS')
    BTC_WALLET_ADDRESS: Optional[str] = Field(None, validation_alias='BTC_WALLET_ADDRESS')
    PAYMENT_EXPIRY_HOURS: int = Field(2, validation_alias='PAYMENT_EXPIRY_HOURS', ge=1, le=72)
    PAYMENT_WEBHOOK_SECRET: Optional[str] = Field(None, validation_alias='PAYMENT_WEBHOOK_SECRET')
    PAYMENT_REQUIRED_CONFIRMATIONS: int = Field(12, validation_alias='PAYMENT_REQUIRED_CONFIRMATIONS', ge=1, le=100)
    
    # Notification Settings
    NOTIFICATION_QUEUE_SIZE: int = Field(100, validation_alias='NOTIFICATION_QUEUE_SIZE')
    NOTIFICATION_BATCH_SIZE: int = Field(10, validation_alias='NOTIFICATION_BATCH_SIZE')
    NOTIFICATION_RETRY_ATTEMPTS: int = Field(3, validation_alias='NOTIFICATION_RETRY_ATTEMPTS')
    
    # Monitoring
    METRICS_ENABLED: bool = Field(True, validation_alias='METRICS_ENABLED')
    METRICS_PORT: int = Field(9090, validation_alias='METRICS_PORT')
    SENTRY_DSN: Optional[str] = Field(None, validation_alias='SENTRY_DSN')
    
    # Logging
    LOG_LEVEL: str = Field("INFO", validation_alias='LOG_LEVEL')
    LOG_FORMAT: str = Field(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        validation_alias='LOG_FORMAT'
    )
    LOG_FILE: Optional[str] = Field(None, validation_alias='LOG_FILE')
    LOG_MAX_BYTES: int = Field(10485760, validation_alias='LOG_MAX_BYTES')
    LOG_BACKUP_COUNT: int = Field(5, validation_alias='LOG_BACKUP_COUNT')
    
    # Feature Flags
    ENABLE_AUTO_TRADING: bool = Field(True, validation_alias='ENABLE_AUTO_TRADING')
    # Blocks every broker-side trade mutation while still allowing read-only
    # calculations and Telegram commands. Enable explicitly for test runs.
    TRADING_DRY_RUN: bool = Field(True, validation_alias='TRADING_DRY_RUN')
    ENABLE_API_ACCESS: bool = Field(True, validation_alias='ENABLE_API_ACCESS')
    ENABLE_WEBHOOKS: bool = Field(False, validation_alias='ENABLE_WEBHOOKS')
    MAX_SIGNAL_AGE_SECONDS: int = Field(300, validation_alias='MAX_SIGNAL_AGE_SECONDS', gt=0, le=86400)
    MAX_FUTURE_SIGNAL_SKEW_SECONDS: int = Field(30, validation_alias='MAX_FUTURE_SIGNAL_SKEW_SECONDS', ge=0, le=3600)
    TRADINGVIEW_WEBHOOK_SECRET: Optional[str] = Field(None, validation_alias='TRADINGVIEW_WEBHOOK_SECRET')
    # A webhook secret is bound to one configured Telegram account; identity is never accepted from payloads.
    TRADINGVIEW_TELEGRAM_ID: Optional[int] = Field(None, validation_alias='TRADINGVIEW_TELEGRAM_ID')
    # When enabled, a validated TradingView signal is fanned out to active paid/trial users.
    TRADINGVIEW_BROADCAST_TO_SUBSCRIBERS: bool = Field(False, validation_alias='TRADINGVIEW_BROADCAST_TO_SUBSCRIBERS')
    # Optional second Telegram channel for public execution summaries.
    TRADE_RESULTS_CHANNEL_ID: Optional[int] = Field(None, validation_alias='TRADE_RESULTS_CHANNEL_ID')
    TRADINGVIEW_SYMBOL_MAP: Dict[str, str] = Field(default={}, validation_alias='TRADINGVIEW_SYMBOL_MAP')
    TELEGRAM_SIGNAL_CHANNEL_IDS: List[int] = Field(default=[], validation_alias='TELEGRAM_SIGNAL_CHANNEL_IDS')
    TRADINGVIEW_WEBHOOK_HOST: str = Field('0.0.0.0', validation_alias='TRADINGVIEW_WEBHOOK_HOST')
    TRADINGVIEW_WEBHOOK_PORT: int = Field(8080, validation_alias='TRADINGVIEW_WEBHOOK_PORT', ge=1, le=65535)
    ENABLE_MULTIPLE_TPS: bool = Field(True, validation_alias='ENABLE_MULTIPLE_TPS')
    USE_GATEWAY: bool = Field(
        default=True,
        validation_alias='USE_GATEWAY'
    )
    GATEWAY_ONLY: bool = Field(
        default=False,
        validation_alias='GATEWAY_ONLY'
    )
    
    # Payment Processing (if using Stripe)
    STRIPE_API_KEY: Optional[str] = Field(None, validation_alias='STRIPE_API_KEY')
    STRIPE_WEBHOOK_SECRET: Optional[str] = Field(None, validation_alias='STRIPE_WEBHOOK_SECRET')

    @field_validator('TRADINGVIEW_SYMBOL_MAP', mode='before')
    @classmethod
    def parse_tradingview_symbol_map(cls, value):
        if value is None or value == '':
            return {}
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                raise ValueError('TRADINGVIEW_SYMBOL_MAP must be JSON')
        if not isinstance(value, dict):
            raise ValueError('TRADINGVIEW_SYMBOL_MAP must be an object')
        return {str(key).upper().strip(): str(val).upper().strip() for key, val in value.items()}

    @field_validator('TELEGRAM_SIGNAL_CHANNEL_IDS', mode='before')
    @classmethod
    def parse_channel_ids(cls, value):
        if value is None or value == '':
            return []
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                value = [part.strip() for part in value.split(',') if part.strip()]
        return [int(item) for item in value]


# Create global settings instance
settings = Settings()

# Validate critical settings
