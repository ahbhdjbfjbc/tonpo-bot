# fx/services/auth.py
"""
Authentication and encryption services
"""
import hashlib
import hmac
import json
import secrets
import time
from urllib.parse import parse_qsl
from datetime import datetime, timedelta
from typing import Optional, Tuple, Dict, Any
import jwt
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import logging
import os
from sqlalchemy.orm import Session

from database.repositories import UserRepository
from config.settings import settings

logger = logging.getLogger(__name__)


class EncryptionService:
    """
    Handles encryption/decryption of sensitive data
    Uses Fernet (symmetric encryption) for MT5 passwords
    """
    
    def __init__(self):
        key = getattr(settings, 'ENCRYPTION_KEY', None)
        if not key:
            raise RuntimeError('ENCRYPTION_KEY must be configured before credential encryption is used')
        try:
            self.cipher = Fernet(key.encode('ascii'))
        except (AttributeError, UnicodeEncodeError, ValueError, TypeError) as exc:
            raise RuntimeError('ENCRYPTION_KEY is invalid; refusing credential encryption') from exc
    
    def encrypt(self, data: str) -> str:
        """Encrypt sensitive data"""
        if not data:
            return ""
        encrypted = self.cipher.encrypt(data.encode())
        return encrypted.decode()
    
    def decrypt(self, encrypted_data: str) -> str:
        """Decrypt sensitive data"""
        if not encrypted_data:
            return ""
        decrypted = self.cipher.decrypt(encrypted_data.encode())
        return decrypted.decode()


GATEWAY_CREDENTIAL_PREFIX = 'fernet:v1:'


def encrypt_gateway_api_key(value: Optional[str]) -> Optional[str]:
    """Encrypt a gateway key before persistence; never store new plaintext keys."""
    if not value:
        return value
    if value.startswith(GATEWAY_CREDENTIAL_PREFIX):
        return value
    return GATEWAY_CREDENTIAL_PREFIX + EncryptionService().encrypt(value)


def decrypt_gateway_api_key(value: Optional[str]) -> str:
    """Return only encrypted gateway keys; legacy plaintext is fail-closed."""
    if not value or not value.startswith(GATEWAY_CREDENTIAL_PREFIX):
        raise RuntimeError('Stored gateway credential is not encrypted; refusing to use it')
    encrypted = value[len(GATEWAY_CREDENTIAL_PREFIX):]
    return EncryptionService().decrypt(encrypted)
    
    @staticmethod
    def hash_password(password: str, salt: Optional[bytes] = None) -> Tuple[bytes, bytes]:
        """Hash a password using PBKDF2"""
        if salt is None:
            salt = os.urandom(16)
        
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        key = kdf.derive(password.encode())
        return key, salt
    
    @staticmethod
    def verify_password(password: str, key: bytes, salt: bytes) -> bool:
        """Verify a password against a hash"""
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        try:
            kdf.verify(password.encode(), key)
            return True
        except Exception:
            return False


class AuthService:
    """
    Handles user authentication, API keys, and JWT tokens
    """
    
    def __init__(self, db_session: Session):
        self.db = db_session
        self.user_repo = UserRepository(db_session)
        self.encryption = None
        self.jwt_secret = getattr(settings, 'JWT_SECRET', None) or os.getenv('JWT_SECRET')
        if not self.jwt_secret:
            raise RuntimeError('JWT_SECRET must be configured before authentication is used')
        self.jwt_algorithm = "HS256"
    
    def verify_telegram_user(self, telegram_id: int, username: str) -> bool:
        """
        Verify if a Telegram user is authorized
        Returns True if user exists and is active
        """
        user = self.user_repo.get_by_telegram_id(telegram_id)
        if not user:
            logger.info(f"Unknown Telegram user attempted access: {telegram_id}")
            return False
        
        if not user.is_active or user.is_banned:
            logger.warning(f"Inactive/banned user attempted access: {telegram_id}")
            return False
        
        return True
    
    def create_api_key(self, user_id: int) -> Optional[str]:
        """
        Generate a new API key for a user
        """
        from database.repositories import SettingsRepository
        settings_repo = SettingsRepository(self.db)
        return settings_repo.generate_api_key(user_id)
    
    def validate_api_key(self, api_key: str) -> Optional[Dict[str, Any]]:
        """
        Validate an API key and return user info
        """
        from database.models import UserSettings, User
        
        settings = self.db.query(UserSettings).filter(
            UserSettings.api_key == api_key,
            UserSettings.api_enabled == True
        ).first()
        
        if not settings:
            return None
        
        user = self.db.query(User).filter(User.id == settings.user_id).first()
        if not user or not user.is_active or user.is_banned:
            return None
        
        return {
            'user_id': user.id,
            'telegram_id': user.telegram_id,
            'subscription_tier': user.subscription_tier
        }

    def verify_telegram_webapp_init_data(
        self, init_data: str, *, max_age_seconds: int = 86400,
        now: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """Validate Telegram Web App initData without trusting browser fields."""
        if not isinstance(init_data, str) or not init_data or len(init_data) > 4096:
            logger.warning("Telegram WebApp initData rejected: invalid type, empty value, or length")
            return None
        try:
            pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True)
        except ValueError:
            logger.warning("Telegram WebApp initData rejected: malformed query string")
            return None
        values: Dict[str, str] = {}
        for key, value in pairs:
            if key in values:
                logger.warning("Telegram WebApp initData rejected: duplicate field=%s", key)
                return None
            values[key] = value
        provided_hash = values.pop('hash', None)
        if not provided_hash or len(provided_hash) != 64:
            logger.warning("Telegram WebApp initData rejected: missing or invalid hash format")
            return None

        data_check_string = '\n'.join(f'{key}={values[key]}' for key in sorted(values))
        secret_key = hmac.new(
            b'WebAppData',
            str(getattr(settings, 'BOT_TOKEN', '')).encode('utf-8'),
            hashlib.sha256,
        ).digest()
        expected_hash = hmac.new(
            secret_key, data_check_string.encode('utf-8'), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected_hash, provided_hash):
            logger.warning("Telegram WebApp initData rejected: hash mismatch")
            return None

        try:
            auth_date = int(values['auth_date'])
            user_data = json.loads(values['user'])
            telegram_id = int(user_data['id'])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            logger.warning("Telegram WebApp initData rejected: missing or invalid auth_date/user")
            return None
        if not isinstance(user_data, dict) or telegram_id <= 0:
            logger.warning("Telegram WebApp initData rejected: invalid Telegram user id")
            return None
        current_time = int(time.time() if now is None else now)
        age = current_time - auth_date
        if age < -300 or age > int(max_age_seconds):
            logger.warning("Telegram WebApp initData rejected: auth_date outside allowed age")
            return None
        return {'telegram_id': telegram_id, 'user': user_data, 'auth_date': auth_date}
    
    def generate_jwt(self, user_id: int, expires_delta: Optional[timedelta] = None) -> str:
        """
        Generate a JWT token for a user
        """
        if expires_delta:
            expire = datetime.utcnow() + expires_delta
        else:
            expire = datetime.utcnow() + timedelta(hours=24)
        
        to_encode = {
            "user_id": user_id,
            "exp": expire,
            "iat": datetime.utcnow()
        }
        
        return jwt.encode(to_encode, self.jwt_secret, algorithm=self.jwt_algorithm)
    
    def verify_jwt(self, token: str) -> Optional[Dict[str, Any]]:
        """
        Verify a JWT token and return the payload
        """
        try:
            payload = jwt.decode(token, self.jwt_secret, algorithms=[self.jwt_algorithm])
            return payload
        except jwt.ExpiredSignatureError:
            logger.warning("JWT token expired")
            return None
        except jwt.InvalidTokenError:
            logger.warning("Invalid JWT token")
            return None
    
    def validate_mt5_credentials(self, account: str, password: str, server: str) -> Tuple[bool, str]:
        """
        Validate MT5 credentials by attempting connection
        This is a stub - actual validation happens in mt5_manager
        """
        # This will be called by MT5ConnectionManager
        # Returning True/False with message
        pass
    
    def _encryption_service(self) -> EncryptionService:
        if self.encryption is None:
            self.encryption = EncryptionService()
        return self.encryption

    def encrypt_mt5_password(self, password: str) -> str:
        """Encrypt MT5 password for storage"""
        return self._encryption_service().encrypt(password)

    def decrypt_mt5_password(self, encrypted: str) -> str:
        """Decrypt MT5 password for use"""
        return self._encryption_service().decrypt(encrypted)
    
    def generate_csrf_token(self) -> str:
        """Generate a CSRF token for web forms"""
        return secrets.token_urlsafe(32)
    
    def verify_hmac(self, secret: str, data: str, signature: str) -> bool:
        """Verify HMAC signature for webhooks"""
        expected = hmac.new(
            secret.encode(),
            data.encode(),
            hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature)
