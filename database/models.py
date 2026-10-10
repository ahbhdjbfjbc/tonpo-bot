# fx/database/models.py
"""
Database models for FX Signal Copier
"""
from sqlalchemy import (
    Column, Integer, BigInteger, String, Float, DateTime, Boolean, 
    JSON, ForeignKey, Text, Index, UniqueConstraint, Numeric
)
from sqlalchemy.orm import relationship, validates
from sqlalchemy.sql import func
from datetime import datetime
import uuid
import re

from .database import Base


class User(Base):
    """User model - stores Telegram users and their MT5 credentials"""
    __tablename__ = 'users'
    
    # Primary key
    id = Column(Integer, primary_key=True)
    uuid = Column(String(36), unique=True, default=lambda: str(uuid.uuid4()), nullable=False)
    
    # Telegram info
    telegram_id = Column(BigInteger, unique=True, nullable=False, index=True)
    telegram_username = Column(String(100), index=True)
    first_name = Column(String(100))
    last_name = Column(String(100))
    language_code = Column(String(10), default='ar', server_default='ar')
    
    # Legacy MT5 credential columns retained for schema compatibility.
    mt5_account_id = Column(String(50), nullable=True)
    # Current registration forwards passwords to Tonpo and does not persist them.
    mt5_password = Column(Text, nullable=True)
    mt5_server = Column(String(100), nullable=True)
    metaapi_token = Column(Text, nullable=True)  # Optional personal token
    
    # Trial tracking
    trial_used = Column(Boolean, default=False, nullable=False)
    trial_start = Column(DateTime, nullable=True)
    trial_end = Column(DateTime, nullable=True)
    
    # Payment history (JSON array)
    payment_history = Column(JSON, default=list)
    
    # CMG Gateway credentials (persist across restarts)
    gateway_user_id = Column(String(64), nullable=True, index=True)
    # Present in migration 008; retained here so ORM/runtime restoration uses
    # the same persisted account identifier as GatewayManager.
    gateway_account_id = Column(String(64), nullable=True, index=True)
    gateway_api_key = Column(Text, nullable=True)
    
    # Trading preferences
    default_risk_factor = Column(Float, default=0.01, nullable=False)
    max_position_size = Column(Float, default=10.0, nullable=False)
    allowed_symbols = Column(JSON, default=list)  # Empty list = all symbols
    blocked_symbols = Column(JSON, default=list)
    
    # Trade modes
    TRADE_MODES = ['manual', 'semi_auto', 'auto']
    trade_mode = Column(String(20), default='manual', nullable=False)
    
    # Account status
    is_active = Column(Boolean, default=True, nullable=False)
    is_verified = Column(Boolean, default=False, nullable=False)
    is_banned = Column(Boolean, default=False, nullable=False)
    ban_reason = Column(String(200), nullable=True)
    
    # Subscription
    subscription_tier = Column(String(50), default='free', nullable=False)
    subscription_expiry = Column(DateTime, nullable=True)
    subscription_features = Column(JSON, default=dict)
    
    # Per-user trading mode: 'demo' | 'live' (default demo; independent of TRADING_DRY_RUN)
    trading_mode = Column(String(10), nullable=False, default='demo', server_default='demo', index=True)
    
    # MetaTrader connection status
    mt_connected = Column(Boolean, default=False)
    last_connected = Column(DateTime, nullable=True)
    connection_error = Column(String(200), nullable=True)
    connection_attempts = Column(Integer, default=0)
    
    # Statistics
    total_trades = Column(Integer, default=0)
    total_volume = Column(Float, default=0)
    winning_trades = Column(Integer, default=0)
    losing_trades = Column(Integer, default=0)
    total_pips = Column(Float, default=0)
    
    # Rate limiting
    daily_trades = Column(Integer, default=0)
    last_trade_date = Column(DateTime, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, onupdate=func.now())
    last_active = Column(DateTime, nullable=True)
    
    # Relationships
    trades = relationship("Trade", back_populates="user", cascade="all, delete-orphan")
    settings = relationship("UserSettings", back_populates="user", uselist=False, cascade="all, delete-orphan")
    connection_logs = relationship("ConnectionLog", back_populates="user", cascade="all, delete-orphan")
    engine_instances = relationship("EngineInstance", back_populates="user", cascade="all, delete-orphan")
    notifications = relationship("Notification", back_populates="user", cascade="all, delete-orphan")
    
    # Indexes
    __table_args__ = (
        Index('idx_user_subscription', 'subscription_tier', 'subscription_expiry'),
        Index('idx_user_active', 'is_active', 'is_verified'),
    )
    
    @validates('telegram_username')
    def validate_username(self, key, value):
        """Validate telegram username format"""
        if value and not re.match(r'^[a-zA-Z0-9_]{5,32}$', value):
            raise ValueError("Invalid telegram username format")
        return value
    
    @validates('default_risk_factor')
    def validate_risk(self, key, value):
        """Validate risk factor is between 0.001 and 0.1 (0.1% to 10%)"""
        if not 0.001 <= value <= 0.1:
            raise ValueError("Risk factor must be between 0.001 and 0.1")
        return value
    
    @property
    def full_name(self) -> str:
        """Get user's full name"""
        if self.first_name and self.last_name:
            return f"{self.first_name} {self.last_name}"
        return self.first_name or self.telegram_username or f"User_{self.telegram_id}"
    
    @property
    def is_premium(self) -> bool:
        """Check if user has premium subscription"""
        if not self.subscription_expiry:
            return False
        return self.subscription_expiry > datetime.utcnow() and self.subscription_tier != 'free'
     
    @property
    def is_live_trading(self) -> bool:
        return (self.trading_mode or 'demo').lower() == 'live'

    @property
    def has_gateway_credentials(self) -> bool:
        """Whether the minimum gateway credential pair is configured."""
        return bool(
            self.gateway_user_id
            and self.gateway_api_key
            and self.gateway_api_key.startswith('fernet:v1:')
        )
    
    @property
    def win_rate(self) -> float:
        """Calculate user's win rate"""
        total_closed = self.winning_trades + self.losing_trades
        if total_closed == 0:
            return 0.0
        return (self.winning_trades / total_closed) * 100


class UserSettings(Base):
    """User-specific settings and preferences"""
    __tablename__ = 'user_settings'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), unique=True, nullable=False)
    
    # Notification preferences
    notify_on_trade = Column(Boolean, default=True)
    notify_on_error = Column(Boolean, default=True)
    notify_on_connection = Column(Boolean, default=True)
    notify_daily_report = Column(Boolean, default=False)
    notify_weekly_report = Column(Boolean, default=False)
    notification_hour = Column(Integer, default=9)  # Hour for daily report (UTC)
    
    # Risk overrides per symbol
    symbol_risk_overrides = Column(JSON, default=dict)  # {"XAUUSD": 0.005, "EURUSD": 0.01}
    
    # Auto TP/SL settings
    auto_tp_enabled = Column(Boolean, default=False)
    auto_tp_pips = Column(Integer, nullable=True)
    auto_sl_enabled = Column(Boolean, default=False)
    auto_sl_pips = Column(Integer, nullable=True)
    
    # Trade filters
    min_distance_from_price = Column(Integer, default=0)  # Minimum pips from current price
    max_spread = Column(Float, default=None, nullable=True)  # Maximum allowed spread
    max_slippage = Column(Float, default=None, nullable=True)
    max_volatility = Column(Float, default=None, nullable=True)
    session_start_utc = Column(String(5), default=None, nullable=True)
    session_end_utc = Column(String(5), default=None, nullable=True)
    max_daily_loss = Column(Float, default=None, nullable=True)
    max_drawdown_pct = Column(Float, default=None, nullable=True)
    max_open_positions = Column(Integer, default=None, nullable=True)
    max_open_trades = Column(Integer, default=None, nullable=True)
    peak_equity = Column(Float, default=None, nullable=True)
    max_consecutive_losses = Column(Integer, default=None, nullable=True)
    protection_enabled = Column(Boolean, default=True, nullable=False, server_default='true')
    
    # Display preferences
    decimal_places = Column(Integer, default=2)
    show_pips = Column(Boolean, default=True)
    
    # API access
    api_key = Column(String(64), unique=True, nullable=True)
    api_enabled = Column(Boolean, default=False)
    
    # Timestamps
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())
    
    # Relationships
    user = relationship("User", back_populates="settings")
    
    @property
    def has_api_access(self) -> bool:
        """Check if user has API access enabled"""
        return self.api_enabled and self.api_key is not None


class Trade(Base):
    """Trade model - stores all executed trades"""
    __tablename__ = 'trades'
    
    id = Column(Integer, primary_key=True)
    uuid = Column(String(36), unique=True, default=lambda: str(uuid.uuid4()), nullable=False)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    
    # Trade details
    order_type = Column(String(20), nullable=False)  # Buy, Sell, Buy Limit, etc.
    symbol = Column(String(20), nullable=False, index=True)
    
    # Prices
    entry_price = Column(Numeric(20, 5), nullable=False)
    stop_loss = Column(Numeric(20, 5), nullable=False)
    take_profits = Column(JSON, nullable=False)  # Array of TP prices
    
    # Calculated values
    position_size = Column(Numeric(20, 2), nullable=False)
    risk_percentage = Column(Float, nullable=False)
    risk_amount = Column(Numeric(20, 2), nullable=False)  # In account currency
    potential_reward = Column(Numeric(20, 2), nullable=False)
    
    # Execution details
    mt_order_ids = Column(JSON, default=list)  # Array of MetaTrader order IDs
    execution_results = Column(JSON, default=list, server_default='[]', nullable=False)
    STATUSES = ['pending', 'executed', 'partial', 'unknown', 'failed', 'cancelled']
    status = Column(String(20), default='pending', nullable=False, index=True)
    error_message = Column(Text, nullable=True)
    
    # Signal source
    signal_text = Column(Text, nullable=False)
    signal_hash = Column(String(64), index=True)  # For duplicate detection
    signal_provider = Column(String(100), nullable=True)  # If from signal service
    
    # Performance (will be updated when trade closes)
    exit_price = Column(Numeric(20, 5), nullable=True)
    profit_loss = Column(Numeric(20, 2), nullable=True)
    profit_loss_pips = Column(Integer, nullable=True)
    closed_at = Column(DateTime, nullable=True)
    
    # Timestamps
    executed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, onupdate=func.now())
    
    # Relationships
    user = relationship("User", back_populates="trades")
    
    # Indexes
    __table_args__ = (
        Index('idx_trade_user_status', 'user_id', 'status'),
        Index('idx_trade_created', 'created_at'),
        Index('idx_trade_symbol', 'symbol', 'created_at'),
    )
    
    @property
    def risk_reward_ratio(self) -> float:
        """Calculate risk/reward ratio"""
        if self.risk_amount == 0:
            return 0
        return float(self.potential_reward) / float(self.risk_amount)
    
    @property
    def tp_count(self) -> int:
        """Number of take profit levels"""
        return len(self.take_profits) if self.take_profits else 0


class ConnectionLog(Base):
    """Logs of MetaTrader connection attempts"""
    __tablename__ = 'connection_logs'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    
    # Connection details
    status = Column(String(20), nullable=False)  # success, failed, timeout
    error = Column(Text, nullable=True)
    latency_ms = Column(Integer, nullable=True)
    
    # Connection info
    server = Column(String(100), nullable=True)
    account_type = Column(String(20), nullable=True)  # demo, real
    
    # Timestamps
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    
    # Relationships
    user = relationship("User", back_populates="connection_logs")
    
    __table_args__ = (
        Index('idx_connection_user_date', 'user_id', 'created_at'),
    )


class EngineInstance(Base):
    """Durable one-user-to-one-MT5-engine binding.

    The API key is encrypted with the existing Fernet credential service. The
    table stores an account reference, never an MT5 password.
    """
    __tablename__ = 'engine_instances'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    engine_instance_id = Column(String(128), nullable=False, unique=True)
    provider = Column(String(32), nullable=False, default='metadocker', server_default='metadocker')
    endpoint = Column(String(255), nullable=False)
    account_reference = Column(String(100), nullable=False)
    api_key_ciphertext = Column(Text, nullable=False)
    engine_version = Column(String(64), nullable=True)
    status = Column(String(24), nullable=False, default='unknown', server_default='unknown')
    provision_status = Column(String(24), nullable=False, default='active', server_default='active')
    last_health_at = Column(DateTime, nullable=True)
    last_session = Column(Integer, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default='true')
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, onupdate=func.now())

    user = relationship("User", back_populates="engine_instances")

    __table_args__ = (
        UniqueConstraint('user_id', 'account_reference', name='uq_engine_user_account'),
        Index('idx_engine_user_active', 'user_id', 'is_active'),
    )


class TradeChannelPublication(Base):
    """Durable outbox state for the central executed-trades channel."""
    __tablename__ = 'trade_channel_publications'

    id = Column(Integer, primary_key=True)
    signal_receipt_id = Column(Integer, ForeignKey('signal_receipts.id', ondelete='CASCADE'), nullable=False, unique=True)
    trade_uuid = Column(String(36), nullable=True, index=True)
    symbol = Column(String(32), nullable=False)
    order_type = Column(String(32), nullable=False)
    position_size = Column(Float, nullable=True)
    entry_price = Column(Numeric(20, 5), nullable=True)
    stop_loss = Column(Numeric(20, 5), nullable=True)
    take_profits = Column(JSON, nullable=True)
    status = Column(String(20), nullable=False, default='pending', server_default='pending')
    telegram_message_id = Column(BigInteger, nullable=True)
    attempts = Column(Integer, nullable=False, default=0, server_default='0')
    last_error = Column(String(255), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    published_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, onupdate=func.now())

    __table_args__ = (
        Index('idx_trade_publication_status', 'status', 'created_at'),
    )


class Notification(Base):
    """User notifications"""
    __tablename__ = 'notifications'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    
    # Notification content
    TYPES = ['info', 'success', 'warning', 'error']
    type = Column(String(20), default='info', nullable=False)
    title = Column(String(200), nullable=False)
    message = Column(Text, nullable=False)
    data = Column(JSON, default=dict)  # Additional data
    event_key = Column(String(160), nullable=True, index=True)
    
    # Delivery
    is_read = Column(Boolean, default=False)
    is_delivered = Column(Boolean, default=False)
    delivered_at = Column(DateTime, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    
    # Relationships
    user = relationship("User", back_populates="notifications")
    
    __table_args__ = (
        Index('idx_notification_user_read', 'user_id', 'is_read'),
    )


class SubscriptionPlan(Base):
    """Available subscription plans"""
    __tablename__ = 'subscription_plans'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(50), unique=True, nullable=False)
    tier = Column(String(20), unique=True, nullable=False)  # free, basic, pro, enterprise
    
    # Pricing
    price_monthly = Column(Numeric(10, 2), nullable=False)
    price_yearly = Column(Numeric(10, 2), nullable=False)
    currency = Column(String(3), default='USD')
    
    # Features
    max_trades_per_day = Column(Integer, default=10)
    max_position_size = Column(Float, default=1.0)
    max_symbols = Column(Integer, default=30)  # 0 = unlimited
    supports_multiple_tps = Column(Boolean, default=True)
    supports_auto_trading = Column(Boolean, default=False)
    supports_api = Column(Boolean, default=False)
    support_priority = Column(String(20), default='normal')
    
    # Limits
    max_connections = Column(Integer, default=1)
    rate_limit_per_second = Column(Integer, default=1)
    
    # Description
    description = Column(Text, nullable=True)
    features = Column(JSON, default=list)  # List of feature descriptions
    
    # Stripe integration
    stripe_price_id_monthly = Column(String(100), nullable=True)
    stripe_price_id_yearly = Column(String(100), nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())
    
    @property
    def is_free(self) -> bool:
        """Check if this is a free plan"""
        return self.tier == 'free'

    def _feature_dict(self):
        if isinstance(self.features, dict):
            return dict(self.features)
        return {'descriptions': list(self.features)} if self.features else {}

    def _admin_metadata(self):
        return dict(self._feature_dict().get('_admin', {}))

    @property
    def is_active(self) -> bool:
        return self._admin_metadata().get('is_active', True)

    @is_active.setter
    def is_active(self, value: bool):
        features = self._feature_dict()
        metadata = dict(features.get('_admin', {}))
        metadata['is_active'] = bool(value)
        features['_admin'] = metadata
        self.features = features

    @property
    def is_visible(self) -> bool:
        return self._admin_metadata().get('is_visible', True)

    @is_visible.setter
    def is_visible(self, value: bool):
        features = self._feature_dict()
        metadata = dict(features.get('_admin', {}))
        metadata['is_visible'] = bool(value)
        features['_admin'] = metadata
        self.features = features

    @property
    def trial_eligible(self) -> bool:
        return bool(self._admin_metadata().get("trial_eligible", self.tier != "free"))

    @trial_eligible.setter
    def trial_eligible(self, value: bool):
        features = self._feature_dict()
        metadata = dict(features.get("_admin", {}))
        metadata["trial_eligible"] = bool(value)
        features["_admin"] = metadata
        self.features = features

    @property
    def display_order(self) -> int:
        return int(self._admin_metadata().get('display_order', 0))

    @display_order.setter
    def display_order(self, value: int):
        features = self._feature_dict()
        metadata = dict(features.get('_admin', {}))
        metadata['display_order'] = int(value)
        features['_admin'] = metadata
        self.features = features

class PaymentRequest(Base):
    """Tracks pending and completed crypto payment requests"""
    __tablename__ = 'payment_requests'
    
    id = Column(Integer, primary_key=True)
    uuid = Column(String(36), unique=True, default=lambda: str(uuid.uuid4()), nullable=False)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    
    # What they're paying for
    plan_tier = Column(String(20), nullable=False)
    billing_period = Column(String(10), nullable=False)  # 'monthly' or 'yearly'
    base_amount = Column(Numeric(12, 2), nullable=False)
    unique_amount = Column(Numeric(12, 4), nullable=False)  # Base + unique cents offset
    currency = Column(String(10), nullable=False)  # 'USDT' or 'BTC'
    
    # Wallet info
    wallet_address = Column(String(100), nullable=False)
    network = Column(String(20), nullable=False)  # 'ERC20' or 'BTC'
    
    # Status: pending → submitted → approved | rejected | expired
    status = Column(String(20), nullable=False, default='pending')
    
    # User-submitted proof is untrusted until an admin reviews it.
    tx_hash = Column(String(100), nullable=True)
    confirmed_amount = Column(Numeric(12, 6), nullable=True)
    confirmations = Column(Integer, default=0)
    block_number = Column(BigInteger, nullable=True)
    
    # Timing and manual review audit metadata
    expires_at = Column(DateTime, nullable=False)
    confirmed_at = Column(DateTime, nullable=True)
    activated_at = Column(DateTime, nullable=True)
    proof_submitted_at = Column(DateTime, nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    reviewed_by = Column(BigInteger, nullable=True)
    rejection_reason = Column(String(255), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    
    # Relationships
    user = relationship("User", backref="payment_requests")
    
    __table_args__ = (
        Index('idx_payment_status', 'status'),
        Index('idx_payment_unique_amount', 'unique_amount', 'currency', 'status'),
        Index('idx_payment_expires', 'expires_at', 'status'),
        Index(
            'uq_payment_network_tx_hash',
            'network', 'tx_hash',
            unique=True,
            postgresql_where=tx_hash.isnot(None),
            sqlite_where=tx_hash.isnot(None),
        ),
    )
    
    @property
    def is_expired(self) -> bool:
        return self.status == 'pending' and datetime.utcnow() > self.expires_at
    
    @property
    def is_pending(self) -> bool:
        return self.status == 'pending' and datetime.utcnow() <= self.expires_at


class ApiUsage(Base):
    """API usage tracking"""
    __tablename__ = 'api_usage'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    api_key = Column(String(64), nullable=False, index=True)
    
    # Usage
    endpoint = Column(String(100), nullable=False)
    method = Column(String(10), nullable=False)
    status_code = Column(Integer, nullable=False)
    response_time_ms = Column(Integer, nullable=False)
    
    # Request info
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    
    __table_args__ = (
        Index('idx_api_user_date', 'user_id', 'created_at'),
    )


class SystemMetric(Base):
    """System-wide metrics for monitoring"""
    __tablename__ = 'system_metrics'
    
    id = Column(Integer, primary_key=True)
    metric_name = Column(String(100), nullable=False, index=True)
    metric_value = Column(Float, nullable=False)
    
    # Tags for filtering
    tags = Column(JSON, default=dict)
    
    # Timestamps
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    
    __table_args__ = (
        Index('idx_metric_name_date', 'metric_name', 'created_at'),
    )

class BotPersistenceStore(Base):
    """Key-value store for PTB conversation/user/chat/bot state (replaces pickle file)"""
    __tablename__ = 'bot_persistence_store'

    id    = Column(Integer, primary_key=True)
    key   = Column(String(100), nullable=False, unique=True, index=True)
    value = Column(Text, nullable=False)

    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


class SignalReceipt(Base):
    """Durable idempotency/audit state for inbound signals."""
    __tablename__ = 'signal_receipts'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=True, index=True)
    source = Column(String(32), nullable=False)
    idempotency_key = Column(String(64), nullable=False)
    signal_text = Column(Text, nullable=False)
    status = Column(String(24), nullable=False, default='received')
    rejection_reason = Column(String(255), nullable=True)
    news_status = Column(String(24), nullable=True)
    validation_status = Column(String(24), nullable=True)
    risk_status = Column(String(24), nullable=True)
    final_decision = Column(String(32), nullable=True)
    risk_reason = Column(String(255), nullable=True)
    protection_reason = Column(String(255), nullable=True)
    signal_id = Column(String(180), nullable=True, index=True)
    account_id = Column(String(64), nullable=True, index=True)
    direction = Column(String(16), nullable=True)
    entry_price = Column(Numeric(20, 5), nullable=True)
    stop_loss = Column(Numeric(20, 5), nullable=True)
    take_profits = Column(JSON, nullable=True)
    signal_timestamp = Column(DateTime, nullable=True)
    execution_latency_ms = Column(Float, nullable=True)
    trade_uuid = Column(String(36), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, onupdate=func.now())
    __table_args__ = (UniqueConstraint('user_id', 'idempotency_key', name='uq_signal_receipt_user_key'),)


class AdminRole(Base):
    """Optional database-backed admin roles; configured IDs remain super-admins."""
    __tablename__ = 'admin_roles'

    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False, index=True)
    role = Column(String(32), nullable=False, default='ADMIN')
    permissions = Column(JSON, nullable=False, default=list, server_default='[]')
    is_active = Column(Boolean, nullable=False, default=True, server_default='true')
    created_by = Column(BigInteger, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())


class AdminAuditLog(Base):
    """Append-only audit records for privileged admin actions (never credentials)."""
    __tablename__ = 'admin_audit_logs'

    id = Column(Integer, primary_key=True)
    admin_telegram_id = Column(BigInteger, nullable=False, index=True)
    role = Column(String(32), nullable=False)
    action = Column(String(80), nullable=False, index=True)
    target_type = Column(String(40), nullable=True)
    target_id = Column(String(100), nullable=True)
    old_value = Column(JSON, nullable=True)
    new_value = Column(JSON, nullable=True)
    result = Column(String(20), nullable=False)
    failure_reason = Column(String(200), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now(), index=True)




class UserAuditLog(Base):
    """Append-only audit for user-initiated settings (no secrets)."""
    __tablename__ = 'user_audit_logs'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)
    telegram_id = Column(BigInteger, nullable=False, index=True)
    action = Column(String(80), nullable=False, index=True)
    old_value = Column(JSON, nullable=True)
    new_value = Column(JSON, nullable=True)
    source = Column(String(40), nullable=True)  # web | telegram
    result = Column(String(20), nullable=False, default='ok')
    failure_reason = Column(String(200), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now(), index=True)

class AdminOffer(Base):
    """Non-financial plan/feature offer; deliberately has no discount or payment fields."""
    __tablename__ = 'admin_offers'

    id = Column(Integer, primary_key=True)
    code = Column(String(48), unique=True, nullable=True, index=True)
    title = Column(String(120), nullable=False)
    description = Column(Text, nullable=True)
    plan_tier = Column(String(20), nullable=True)
    feature = Column(String(80), nullable=True)
    starts_at = Column(DateTime, nullable=True)
    ends_at = Column(DateTime, nullable=True)
    max_uses = Column(Integer, nullable=True)
    uses_count = Column(Integer, nullable=False, default=0, server_default='0')
    target_telegram_ids = Column(JSON, nullable=True)
    is_active = Column(Boolean, nullable=False, default=False, server_default='false')
    created_by = Column(BigInteger, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())


class SupportTicket(Base):
    """Support ticket opened by a user and managed by admins."""
    __tablename__ = 'support_tickets'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)
    telegram_id = Column(BigInteger, nullable=False, index=True)
    subject = Column(String(160), nullable=False)
    status = Column(String(20), nullable=False, default='open', server_default='open', index=True)
    assigned_admin_id = Column(BigInteger, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())
    closed_at = Column(DateTime, nullable=True)


class SupportMessage(Base):
    """Messages attached to a support ticket."""
    __tablename__ = 'support_messages'

    id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey('support_tickets.id', ondelete='CASCADE'), nullable=False, index=True)
    sender_telegram_id = Column(BigInteger, nullable=False)
    sender_role = Column(String(20), nullable=False)
    message = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class Announcement(Base):
    """Admin-authored announcement configuration; never stores secrets."""
    __tablename__ = "announcements"

    id = Column(Integer, primary_key=True)
    title = Column(String(160), nullable=False)
    message = Column(Text, nullable=False)
    enabled = Column(Boolean, nullable=False, default=False, server_default="false")
    audience = Column(JSON, nullable=True)
    starts_at = Column(DateTime, nullable=True)
    ends_at = Column(DateTime, nullable=True)
    created_by = Column(BigInteger, nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())


class AnnouncementDelivery(Base):
    """Persistent at-most-once claim for one user and announcement cycle."""
    __tablename__ = "announcement_deliveries"

    id = Column(Integer, primary_key=True)
    announcement_id = Column(Integer, ForeignKey("announcements.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    cycle_key = Column(String(40), nullable=False)
    status = Column(String(20), nullable=False, default="reserved", server_default="reserved")
    attempted_at = Column(DateTime, nullable=False, server_default=func.now())
    delivered_at = Column(DateTime, nullable=True)
    error_code = Column(String(80), nullable=True)

    __table_args__ = (
        UniqueConstraint("announcement_id", "user_id", "cycle_key", name="uq_announcement_delivery_cycle"),
        Index("ix_announcement_delivery_cycle", "cycle_key"),
    )


class AdminSetting(Base):
    """Safe, non-secret runtime settings such as the emergency execution stop."""
    __tablename__ = 'admin_settings'

    key = Column(String(80), primary_key=True)
    value = Column(String(500), nullable=False)
    updated_by = Column(BigInteger, nullable=True)
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
