# fx/database/db_persistence.py
"""
PostgreSQL-backed persistence for python-telegram-bot.
Replaces PicklePersistence — atomic writes, no corruption on crash.
"""
import json
import logging
from copy import deepcopy
from typing import Any, Dict, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session
from telegram.ext import BasePersistence
from telegram.ext._utils.types import CDCData, ConversationDict, ConversationKey

from database.models import BotPersistenceStore
from database.database import db_manager

logger = logging.getLogger(__name__)

_CONV_KEY   = "conversations"
_USER_KEY   = "user_data"
_CHAT_KEY   = "chat_data"
_BOT_KEY    = "bot_data"
_CALLBACK_KEY = "callback_data"
_BOT_SINGLETON_LOCK_KEY = 731945206403
_SENSITIVE_USER_DATA_KEYS = frozenset({
    'password', 'mt5_password', 'secret', 'webhook_secret',
    'token', 'access_token', 'refresh_token', 'session_token',
    'api_key', 'gateway_api_key', 'apikey', 'credential', 'credentials',
    'private_key', 'privatekey', 'jwt', 'jwt_token',
})


def _sanitize_user_data(value: Any) -> Any:
    """Prevent credentials accidentally placed in Telegram user_data being persisted."""
    if isinstance(value, dict):
        return {
            key: _sanitize_user_data(item)
            for key, item in value.items()
            if str(key).lower().replace('-', '_') not in _SENSITIVE_USER_DATA_KEYS
        }
    if isinstance(value, list):
        return [_sanitize_user_data(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_sanitize_user_data(item) for item in value)
    return value


def _get_db() -> Session:
    return db_manager.get_session()


def _load(key: str) -> Any:
    db = _get_db()
    try:
        row = db.query(BotPersistenceStore).filter_by(key=key).first()
        if row:
            return json.loads(row.value)
        return None
    except Exception as e:
        logger.error("DBPersistence load error for key=%s (%s)", key, type(e).__name__)
        return None
    finally:
        db.close()


def _save(key: str, value: Any) -> None:
    db = _get_db()
    try:
        row = db.query(BotPersistenceStore).filter_by(key=key).first()
        serialized = json.dumps(value, default=str)
        if row:
            row.value = serialized
        else:
            row = BotPersistenceStore(key=key, value=serialized)
            db.add(row)
        db.commit()
    except Exception as e:
        logger.error("DBPersistence save error for key=%s (%s)", key, type(e).__name__)
        db.rollback()
    finally:
        db.close()


class DBPersistence(BasePersistence):
    """
    PostgreSQL-backed persistence for PTB.
    All reads/writes go to the bot_persistence_store table. The in-memory
    snapshot is intentionally single-instance; PostgreSQL advisory locking
    prevents two bot processes from overwriting one another's state.
    """

    def __init__(self):
        super().__init__()
        self._conversations: Dict = {}
        self._user_data: Dict     = {}
        self._chat_data: Dict     = {}
        self._bot_data: Dict      = {}
        self._callback_data: Optional[CDCData] = None
        self._loaded = False
        self._instance_lock_connection = None

    def acquire_single_instance_lock(self) -> None:
        """Hold a PostgreSQL session lock for the bot's entire process lifetime."""
        if self._instance_lock_connection is not None:
            return
        engine = getattr(db_manager, "engine", None)
        if engine is None:
            raise RuntimeError("Database must be initialized before bot startup")
        if engine.dialect.name != "postgresql":
            logger.warning("DBPersistence singleton lock requires PostgreSQL; local SQLite is development-only")
            return
        connection = engine.connect()
        try:
            acquired = bool(connection.execute(
                text("SELECT pg_try_advisory_lock(:lock_key)"),
                {"lock_key": _BOT_SINGLETON_LOCK_KEY},
            ).scalar())
            if not acquired:
                raise RuntimeError("Another Telegram bot process already owns DBPersistence")
            self._instance_lock_connection = connection
        except Exception:
            connection.close()
            raise

    def release_single_instance_lock(self) -> None:
        connection, self._instance_lock_connection = self._instance_lock_connection, None
        if connection is None:
            return
        try:
            connection.execute(
                text("SELECT pg_advisory_unlock(:lock_key)"),
                {"lock_key": _BOT_SINGLETON_LOCK_KEY},
            )
        finally:
            connection.close()

    def _ensure_loaded(self):
        if self._loaded:
            return
        try:
            self._conversations  = _load(_CONV_KEY)  or {}
            self._user_data      = {int(k): _sanitize_user_data(v) for k, v in (_load(_USER_KEY)  or {}).items()}
            self._chat_data      = {int(k): v for k, v in (_load(_CHAT_KEY)  or {}).items()}
            self._bot_data       = _load(_BOT_KEY)   or {}
            self._callback_data  = _load(_CALLBACK_KEY)
            self._loaded = True
            logger.info("DBPersistence: state loaded from database")
        except Exception as e:
            logger.error("DBPersistence failed to load persisted state (%s)", type(e).__name__)
            self._loaded = True  # don't retry on every call

    # ── Conversations ──────────────────────────────────────────────────────────

    async def get_conversations(self, name: str) -> ConversationDict:
        self._ensure_loaded()
        return self._conversations.get(name, {})

    async def update_conversation(
        self, name: str, key: ConversationKey, new_state: Optional[object]
    ) -> None:
        self._ensure_loaded()
        if name not in self._conversations:
            self._conversations[name] = {}
        if new_state is None:
            self._conversations[name].pop(key, None)
        else:
            # Guard: never persist a coroutine (would cause TypeError on pickle too)
            if hasattr(new_state, 'cr_frame'):
                logger.error(
                    f"DBPersistence: refusing to save coroutine as conversation state "
                    f"for '{name}'. Did you forget 'await'?"
                )
                return
            self._conversations[name][key] = new_state
        # Serialize keys as strings (tuples aren't JSON-serializable)
        serializable = {
            conv_name: {str(k): v for k, v in states.items()}
            for conv_name, states in self._conversations.items()
        }
        _save(_CONV_KEY, serializable)

    # ── User data ──────────────────────────────────────────────────────────────

    async def get_user_data(self) -> Dict[int, Dict]:
        self._ensure_loaded()
        return deepcopy(self._user_data)

    async def update_user_data(self, user_id: int, data: Dict) -> None:
        self._ensure_loaded()
        self._user_data[user_id] = _sanitize_user_data(data)
        _save(_USER_KEY, self._user_data)

    async def refresh_user_data(self, user_id: int, user_data: Dict) -> None:
        pass  # in-memory copy is always current

    # ── Chat data ──────────────────────────────────────────────────────────────

    async def get_chat_data(self) -> Dict[int, Dict]:
        self._ensure_loaded()
        return deepcopy(self._chat_data)

    async def update_chat_data(self, chat_id: int, data: Dict) -> None:
        self._ensure_loaded()
        self._chat_data[chat_id] = data
        _save(_CHAT_KEY, self._chat_data)

    async def refresh_chat_data(self, chat_id: int, chat_data: Dict) -> None:
        pass

    # ── Bot data ───────────────────────────────────────────────────────────────

    async def get_bot_data(self) -> Dict:
        self._ensure_loaded()
        return deepcopy(self._bot_data)

    async def update_bot_data(self, data: Dict) -> None:
        self._ensure_loaded()
        self._bot_data = data
        _save(_BOT_KEY, self._bot_data)

    async def refresh_bot_data(self, bot_data: Dict) -> None:
        pass

    # ── Callback data ──────────────────────────────────────────────────────────

    async def get_callback_data(self) -> Optional[CDCData]:
        self._ensure_loaded()
        return deepcopy(self._callback_data)

    async def update_callback_data(self, data: CDCData) -> None:
        self._ensure_loaded()
        self._callback_data = data
        _save(_CALLBACK_KEY, data)

    # ── Drop data ──────────────────────────────────────────────────────────────

    async def drop_chat_data(self, chat_id: int) -> None:
        self._chat_data.pop(chat_id, None)
        _save(_CHAT_KEY, self._chat_data)

    async def drop_user_data(self, user_id: int) -> None:
        self._user_data.pop(user_id, None)
        _save(_USER_KEY, self._user_data)

    async def flush(self) -> None:
        """Called on shutdown — all writes are already committed per-update."""
        logger.info("DBPersistence: flush called (no-op, all writes are immediate)")
