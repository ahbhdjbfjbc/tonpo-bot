# fx/services/cache.py
import json
import pickle
from typing import Any, Optional, Dict
from datetime import timedelta
import logging
import redis
from redis.exceptions import RedisError

from config.settings import settings

logger = logging.getLogger(__name__)


class RateLimitUnavailable(RuntimeError):
    """Raised when a protected rate-limit decision cannot be verified."""


_RATE_LIMIT_SCRIPT = """
local limit = tonumber(ARGV[1])
local period = tonumber(ARGV[2])
local current = redis.call('GET', KEYS[1])
if current then
    local numeric = tonumber(current)
    if not numeric then
        return {-1, -1}
    end
    local current_ttl = redis.call('TTL', KEYS[1])
    if numeric >= limit then
        return {0, current_ttl}
    end
end
local count = redis.call('INCR', KEYS[1])
local ttl = redis.call('TTL', KEYS[1])
if count == 1 or ttl < 0 then
    redis.call('EXPIRE', KEYS[1], period)
    ttl = period
end
if count > limit then
    return {0, ttl}
end
return {1, ttl}
"""


class CacheService:
    """
    Redis-based caching service
    """
    
    def __init__(self):
        self.redis_client = None
        self._connect()
    
    def _connect(self):
        """Connect to Redis"""
        redis_url = getattr(settings, "REDIS_URL", None)
        if not redis_url:
            self.redis_client = None
            logger.info("Redis cache disabled: REDIS_URL is not configured")
            return
        try:
            self.redis_client = redis.from_url(
                redis_url,
                decode_responses=False,  # For binary data
                socket_connect_timeout=2,
                socket_timeout=5,
                retry_on_timeout=True
            )
            # Test connection
            self.redis_client.ping()
            logger.info("Connected to Redis")
        except Exception as e:
            logger.error("Failed to connect to Redis (%s)", type(e).__name__)
            self.redis_client = None
    
    def _ensure_connection(self):
        """Ensure Redis connection is alive"""
        if not self.redis_client:
            self._connect()
            if not self.redis_client:
                return False
        return True
    
    def set(self, key: str, value: Any, ttl: Optional[timedelta] = None) -> bool:
        """Set a value in cache"""
        if not self._ensure_connection():
            return False
        
        try:
            # Serialize value
            if isinstance(value, (dict, list)):
                data = json.dumps(value)
            else:
                data = pickle.dumps(value)
            
            # Set with TTL
            if ttl:
                self.redis_client.setex(key, ttl, data)
            else:
                self.redis_client.set(key, data)
            
            return True
        except RedisError as e:
            logger.error("Redis set failed (%s)", type(e).__name__)
            return False
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get a value from cache"""
        if not self._ensure_connection():
            return default
        
        try:
            data = self.redis_client.get(key)
            if not data:
                return default
            
            # Try JSON first
            try:
                return json.loads(data)
            except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
                pass
            
            # Try pickle
            try:
                return pickle.loads(data)
            except:
                return data.decode() if isinstance(data, bytes) else data
                
        except RedisError as e:
            logger.error("Redis get failed (%s)", type(e).__name__)
            return default
    
    def delete(self, key: str) -> bool:
        """Delete a key from cache"""
        if not self._ensure_connection():
            return False
        
        try:
            self.redis_client.delete(key)
            return True
        except RedisError as e:
            logger.error("Redis delete failed (%s)", type(e).__name__)
            return False
    
    def exists(self, key: str) -> bool:
        """Check if key exists"""
        if not self._ensure_connection():
            return False
        
        try:
            return self.redis_client.exists(key) > 0
        except RedisError as e:
            logger.error("Redis exists check failed (%s)", type(e).__name__)
            return False
    
    def increment(self, key: str, amount: int = 1) -> Optional[int]:
        """Increment a counter"""
        if not self._ensure_connection():
            return None
        
        try:
            return self.redis_client.incr(key, amount)
        except RedisError as e:
            logger.error("Redis increment failed (%s)", type(e).__name__)
            return None

    def check_rate_limit(self, key: str, limit: int, period: int) -> tuple[bool, int]:
        """Atomically check and update a protected fixed-window counter."""
        if limit <= 0 or period <= 0:
            raise ValueError("rate-limit limit and period must be positive")
        if not self._ensure_connection():
            raise RateLimitUnavailable("Redis rate-limit state is unavailable")

        try:
            result = self.redis_client.eval(
                _RATE_LIMIT_SCRIPT, 1, key, int(limit), int(period)
            )
        except RedisError as exc:
            logger.error("Redis rate-limit check failed (%s)", type(exc).__name__)
            raise RateLimitUnavailable("Redis rate-limit state is unavailable") from exc

        if not isinstance(result, (list, tuple)) or len(result) != 2:
            logger.error("Redis rate-limit check returned malformed state")
            raise RateLimitUnavailable("Redis rate-limit state is invalid")
        try:
            allowed, retry_after = int(result[0]), int(result[1])
        except (TypeError, ValueError):
            logger.error("Redis rate-limit check returned non-numeric state")
            raise RateLimitUnavailable("Redis rate-limit state is invalid")
        if allowed not in (0, 1) or retry_after < 0:
            logger.error("Redis rate-limit check returned unsafe state")
            raise RateLimitUnavailable("Redis rate-limit state is invalid")
        return bool(allowed), retry_after
    
    def expire(self, key: str, ttl: timedelta) -> bool:
        """Set expiration on a key"""
        if not self._ensure_connection():
            return False
        
        try:
            return self.redis_client.expire(key, int(ttl.total_seconds()))
        except RedisError as e:
            logger.error("Redis expire failed (%s)", type(e).__name__)
            return False
    
    def get_or_set(self, key: str, func, ttl: Optional[timedelta] = None) -> Any:
        """Get from cache or compute and store"""
        # Try cache first
        value = self.get(key)
        if value is not None:
            return value
        
        # Compute value
        value = func()
        if value is not None:
            self.set(key, value, ttl)
        
        return value
    
    def clear_pattern(self, pattern: str) -> int:
        """Clear all keys matching pattern"""
        if not self._ensure_connection():
            return 0
        
        try:
            keys = self.redis_client.keys(pattern)
            if keys:
                return self.redis_client.delete(*keys)
            return 0
        except RedisError as e:
            logger.error("Redis pattern clear failed (%s)", type(e).__name__)
            return 0
    
    def get_stats(self) -> Dict[str, Any]:
        """Get Redis stats"""
        if not self._ensure_connection():
            return {'status': 'disconnected'}
        
        try:
            info = self.redis_client.info()
            return {
                'status': 'connected',
                'used_memory': info.get('used_memory_human', 'unknown'),
                'connected_clients': info.get('connected_clients', 0),
                'total_commands_processed': info.get('total_commands_processed', 0),
                'keyspace_hits': info.get('keyspace_hits', 0),
                'keyspace_misses': info.get('keyspace_misses', 0),
                'uptime_days': info.get('uptime_in_days', 0)
            }
        except Exception as e:
            return {'status': 'error', 'error': 'Redis stats unavailable'}

    def close(self) -> None:
        """Release the Redis connection pool during application shutdown."""
        if self.redis_client is not None:
            try:
                self.redis_client.close()
            finally:
                self.redis_client = None


# Cache key constants
class CacheKeys:
    """Cache key constants"""
    
    # User data
    USER_PREFIX = "user:"
    USER_SETTINGS_PREFIX = "user:settings:"
    USER_STATS_PREFIX = "user:stats:"
    
    # Price data
    PRICE_PREFIX = "price:"
    
    # Rate limiting
    RATE_LIMIT_PREFIX = "ratelimit:"
    
    # Session data
    SESSION_PREFIX = "session:"
    
    # Trade data
    TRADE_PREFIX = "trade:"
    
    @staticmethod
    def user(user_id: int) -> str:
        return f"{CacheKeys.USER_PREFIX}{user_id}"
    
    @staticmethod
    def user_settings(user_id: int) -> str:
        return f"{CacheKeys.USER_SETTINGS_PREFIX}{user_id}"
    
    @staticmethod
    def user_stats(user_id: int) -> str:
        return f"{CacheKeys.USER_STATS_PREFIX}{user_id}"
    
    @staticmethod
    def price(symbol: str) -> str:
        return f"{CacheKeys.PRICE_PREFIX}{symbol}"
    
    @staticmethod
    def rate_limit(user_id: int, action: str) -> str:
        return f"{CacheKeys.RATE_LIMIT_PREFIX}{user_id}:{action}"
    
    @staticmethod
    def session(session_id: str) -> str:
        return f"{CacheKeys.SESSION_PREFIX}{session_id}"
    
    @staticmethod
    def trade(trade_uuid: str) -> str:
        return f"{CacheKeys.TRADE_PREFIX}{trade_uuid}"
