# gateway_client/adapter.py
"""
Gateway adapter — replaces the hand-rolled gateway_client/client.py with
the official cipher_gateway SDK (pip install cipher-gateway).

External interface is unchanged:
  - TonpoConnectionAdapter  — used by trade_executor.py / trading.py
  - GatewayManager            — used by adapter.py / main.py
  - ExecutionProvider         — used by main.py

Internal implementation now delegates entirely to TonpoClient.
"""
import asyncio
import logging
from typing import Optional, Dict, Any, List, Callable

from tonpo import (
    TonpoClient,
    TonpoConfig,
    AccountLoginFailedError,
    AccountTimeoutError,
    TonpoConnectionError,
    TonpoError,
)

from config.settings import settings

logger = logging.getLogger(__name__)


class GatewayCapabilityUnavailable(RuntimeError):
    """Raised when the configured gateway cannot provide required metadata."""



def _execution_result(result: Any) -> Dict[str, Any]:
    """Normalize Tonpo acknowledgements without inventing a successful ticket."""
    ticket = getattr(result, 'ticket', None)
    accepted = bool(getattr(result, 'success', False))
    if not accepted:
        return {'success': False, 'status': 'rejected', 'orderId': None,
                'error': 'Tonpo rejected the order'}
    if not ticket:
        return {'success': False, 'status': 'unknown', 'orderId': None,
                'error': 'Tonpo acknowledged without a verifiable ticket'}
    return {'success': True, 'status': 'accepted', 'orderId': str(ticket)}


# ---------------------------------------------------------------------------
# GatewayConnectionAdapter
# ---------------------------------------------------------------------------
# Wraps one CipherGatewayClient (already authenticated for a single user).
# Methods match what trade_executor.py and trading.py call — untouched.

class TonpoConnectionAdapter:
    def __init__(self, client: TonpoClient, user_id: str):
        self.client  = client
        self.user_id = user_id
        self._connected = True

    async def _request(self, operation: str, method: Callable, *args, **kwargs):
        """Call the gateway without exposing provider errors that may contain credentials."""
        try:
            return await method(*args, **kwargs)
        except Exception as exc:
            logger.error('Gateway operation %s failed (%s)', operation, type(exc).__name__)
            raise RuntimeError(f'Gateway operation failed: {operation}') from None

    # ── Account ──────────────────────────────────────────────────────────────

    async def get_account_information(self) -> Dict[str, Any]:
        info = await self._request('account_info', self.client.get_account_info)
        return {
            'login':        info.login,
            'name':         info.name,
            'balance':      info.balance,
            'equity':       info.equity,
            'margin':       info.margin,
            'free_margin':  info.free_margin,
            'margin_level': info.margin_level,   # computed property on SDK model
            'currency':     info.currency,
            'server':       info.server,
            'leverage':     info.leverage,
            'profit':       info.profit,
        }

    async def get_positions(self) -> List[Dict[str, Any]]:
        positions = await self._request('positions', self.client.get_positions)
        return [{
            'id':           p.ticket,
            'symbol':       p.symbol,
            'type':         p.side,
            'volume':       p.volume,
            'openPrice':    p.open_price,
            'currentPrice': p.current_price,
            'stopLoss':     p.sl,
            'takeProfit':   p.tp,
            'profit':       p.profit,
            'swap':         p.swap,
            'commission':   p.commission,
            'comment':      p.comment,
        } for p in positions]

    async def verify_market_execution(self, order_id: str) -> bool:
        """Verify that Tonpo exposes the acknowledged market ticket as a position."""
        positions = await self.get_positions()
        return any(str(position.get('id')) == str(order_id) for position in positions)

    # ── Market orders ─────────────────────────────────────────────────────────

    async def create_market_buy_order(
        self, symbol: str, volume: float,
        sl: Optional[float] = None, tp: Optional[float] = None,
        comment: Optional[str] = None, magic: Optional[int] = None
    ) -> Dict[str, Any]:
        result = await self._request('market_buy', self.client.place_market_buy,
            symbol, volume=volume, sl=sl, tp=tp, comment=comment, magic=magic
        )
        return _execution_result(result)

    async def create_market_sell_order(
        self, symbol: str, volume: float,
        sl: Optional[float] = None, tp: Optional[float] = None,
        comment: Optional[str] = None, magic: Optional[int] = None
    ) -> Dict[str, Any]:
        result = await self._request('market_sell', self.client.place_market_sell,
            symbol, volume=volume, sl=sl, tp=tp, comment=comment, magic=magic
        )
        return _execution_result(result)

    # ── Limit orders ──────────────────────────────────────────────────────────

    async def create_limit_buy_order(
        self, symbol: str, volume: float, price: float,
        sl: Optional[float] = None, tp: Optional[float] = None,
        comment: Optional[str] = None, magic: Optional[int] = None
    ) -> Dict[str, Any]:
        result = await self._request('limit_buy', self.client.place_limit_buy,
            symbol, volume=volume, price=price, sl=sl, tp=tp,
            comment=comment, magic=magic
        )
        return _execution_result(result)

    async def create_limit_sell_order(
        self, symbol: str, volume: float, price: float,
        sl: Optional[float] = None, tp: Optional[float] = None,
        comment: Optional[str] = None, magic: Optional[int] = None
    ) -> Dict[str, Any]:
        result = await self._request('limit_sell', self.client.place_limit_sell,
            symbol, volume=volume, price=price, sl=sl, tp=tp,
            comment=comment, magic=magic
        )
        return _execution_result(result)

    # ── Stop orders ───────────────────────────────────────────────────────────

    async def create_stop_buy_order(
        self, symbol: str, volume: float, price: float,
        sl: Optional[float] = None, tp: Optional[float] = None,
        comment: Optional[str] = None, magic: Optional[int] = None
    ) -> Dict[str, Any]:
        result = await self._request('stop_buy', self.client.place_stop_buy,
            symbol, volume=volume, price=price, sl=sl, tp=tp,
            comment=comment, magic=magic
        )
        return _execution_result(result)

    async def create_stop_sell_order(
        self, symbol: str, volume: float, price: float,
        sl: Optional[float] = None, tp: Optional[float] = None,
        comment: Optional[str] = None, magic: Optional[int] = None
    ) -> Dict[str, Any]:
        result = await self._request('stop_sell', self.client.place_stop_sell,
            symbol, volume=volume, price=price, sl=sl, tp=tp,
            comment=comment, magic=magic
        )
        return _execution_result(result)

    # ── Position management ───────────────────────────────────────────────────

    async def close_position(self, position_id: str) -> bool:
        result = await self._request('close_position', self.client.close_position, ticket=int(position_id))
        return result.success

    async def modify_position(
        self, position_id: str,
        sl: Optional[float] = None, tp: Optional[float] = None
    ) -> bool:
        result = await self._request('modify_position', self.client.modify_position,
            ticket=int(position_id), sl=sl, tp=tp
        )
        return result.success

    # ── Market data ───────────────────────────────────────────────────────────

    async def get_symbol_price(self, symbol: str) -> Dict[str, float]:
        """
        Get current bid/ask for a symbol.
        Uses the SDK's get_symbol_price which already falls back to the
        WebSocket price cache when the REST endpoint returns zeros.
        """
        try:
            price = await self._request('symbol_price', self.client.get_symbol_price, symbol)
            return {'bid': price.bid, 'ask': price.ask}
        except Exception as exc:
            logger.warning('Market price request failed for %s (%s)', symbol, type(exc).__name__)
            raise RuntimeError(f'Unable to get price for {symbol}') from None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def get_symbol_constraints(self, symbol: str) -> Dict[str, float]:
        """Return authoritative broker contract metadata when supported.

        Tonpo SDK 1.0.4 has no symbol-specification method or response model.
        This explicit capability boundary prevents hardcoded broker assumptions.
        """
        raise GatewayCapabilityUnavailable(
            'Tonpo Gateway/SDK does not expose symbol contract constraints'
        )

    async def close(self):
        """Close this connection's underlying client."""
        self._connected = False
        try:
            await self.client.__aexit__(None, None, None)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# GatewayManager
# ---------------------------------------------------------------------------
# Manages one SDK client per user.  Public interface unchanged from before.

class GatewayManager:
    def __init__(self, tonpo_config: Optional[TonpoConfig] = None):
        self.gateway_config: TonpoConfig = tonpo_config or TonpoConfig()

        # Per-user live clients (created lazily in get_connection)
        self.user_clients:      Dict[int, TonpoClient] = {}
        self.connections: Dict[int, TonpoConnectionAdapter] = {}

        # Credentials loaded from DB on startup or stored after registration
        self.user_api_keys:     Dict[int, str] = {}
        self.user_gateway_ids:  Dict[int, str] = {}
        self.user_account_ids:  Dict[int, str] = {}
        self._registration_inflight: set[int] = set()

        self._ready       = asyncio.Event()
        self._ready_error: Optional[str] = None

        logger.info("GatewayManager initialised")

    async def start(self):
        """Health-check the gateway and mark the manager as ready."""
        logger.info("GatewayManager starting — checking gateway health...")
        try:
            async with TonpoClient.admin(self.gateway_config) as client:
                healthy = await client.health_check()
            if healthy:
                self._ready.set()
                logger.info("GatewayManager ready ✅")
            else:
                self._ready_error = "Gateway health check returned unhealthy"
                logger.error(self._ready_error)
        except Exception as exc:
            self._ready_error = f"Gateway unreachable ({type(exc).__name__})"
            logger.error('Gateway health check failed (%s)', type(exc).__name__)

    async def stop(self):
        """Close all open clients."""
        logger.info("GatewayManager stopping...")
        for telegram_id, client in list(self.user_clients.items()):
            try:
                await client.__aexit__(None, None, None)
            except Exception:
                pass
        self.user_clients.clear()
        self.connections.clear()
        logger.info("GatewayManager stopped")

    async def wait_until_ready(self, timeout: float = 30.0):
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=timeout)
            return True, None
        except asyncio.TimeoutError:
            return False, self._ready_error or "Timeout"

    @property
    def is_ready(self) -> bool:
        return self._ready.is_set()

    # ── User registration ─────────────────────────────────────────────────────

    def _check_connection_entitlement(self, telegram_id: int) -> tuple[bool, str]:
        """Fail closed on entitlement errors and enforce the currently supported one-account binding."""
        from database.database import db_manager
        from database.models import EngineInstance, User
        from services.subscription import SubscriptionService

        if telegram_id in self.user_account_ids:
            return False, "One MT5 account is already connected; additional accounts are not supported yet"

        db = None
        try:
            db = db_manager.get_session()
            user = db.query(User).filter_by(telegram_id=telegram_id).first()
            if user is None:
                # First registration creates the local user only after the
                # gateway succeeds; the product's unregistered/free default is one account.
                return True, ""
            if not user.is_active or user.is_banned:
                return False, "This account is unavailable for gateway registration"

            plan = SubscriptionService(db).get_user_plan(telegram_id)
            limit = int(getattr(plan, "max_connections", 0) or 0)
            if limit < 1:
                return False, "The current plan does not allow gateway connections"

            durable_instances = db.query(EngineInstance).filter_by(
                user_id=user.id, is_active=True
            ).count()
            has_legacy_binding = bool(
                user.gateway_user_id or user.gateway_account_id or user.gateway_api_key
            )
            if has_legacy_binding or durable_instances:
                return False, "One MT5 account is already connected; additional accounts are not supported yet"
            return True, ""
        except Exception as exc:
            if db is not None:
                try:
                    db.rollback()
                except Exception:
                    pass
            logger.error("Gateway connection entitlement check failed (%s)", type(exc).__name__)
            return False, "Unable to verify the plan or existing connections; please retry later"
        finally:
            if db is not None:
                db.close()

    async def register_user(
        self,
        telegram_id: int,
        mt5_account:  str,
        mt5_password: str,
        mt5_server:   str,
    ) -> tuple:
        """
        Register a user with the gateway.
        Returns (success, message, credentials_dict).
        credentials_dict contains: tonpo_user_id, tonpo_api_key, tonpo_account_id
        """
        if telegram_id in self._registration_inflight:
            return False, "An MT5 registration is already in progress", {}
        # This check-and-set has no await and is atomic within the single bot event loop.
        self._registration_inflight.add(telegram_id)
        try:
            allowed, entitlement_error = self._check_connection_entitlement(telegram_id)
            if not allowed:
                return False, entitlement_error, {}

            # Step 1: create a gateway user (no auth required)
            async with TonpoClient.admin(self.gateway_config) as client:
                user_creds = await client.create_user()

            api_key          = user_creds.api_key
            tonpo_user_id  = user_creds.gateway_user_id

            # Step 2 + 3 + 4: provision account and wait for MT5 to connect
            async with TonpoClient.for_user(self.gateway_config, api_key) as client:
                account = await client.create_account(
                    mt5_login    = mt5_account,
                    mt5_password = mt5_password,
                    mt5_server   = mt5_server,
                )
                tonpo_account_id = account.account_id

                try:
                    await client.wait_for_active(tonpo_account_id, timeout=180)
                except AccountLoginFailedError as e:
                    # Clean up — wrong credentials, no point keeping the account
                    try:
                        await client.delete_account(tonpo_account_id)
                    except Exception:
                        pass
                    return False, "MT5 login failed; verify credentials with your broker", {}
                except AccountTimeoutError as e:
                    try:
                        await client.delete_account(tonpo_account_id)
                    except Exception:
                        pass
                    return False, "MT5 connection timed out", {}

            # Step 5: store credentials in memory
            self.user_gateway_ids[telegram_id] = tonpo_user_id
            self.user_api_keys[telegram_id]    = api_key
            self.user_account_ids[telegram_id] = tonpo_account_id

            logger.info(
                f"User {telegram_id} registered "
                f"(gw_id={tonpo_user_id}, account={tonpo_account_id})"
            )
            return True, "Connected successfully", {
                'gateway_user_id':    tonpo_user_id,
                'gateway_api_key':   api_key,
                'gateway_account_id': tonpo_account_id,
            }

        except TonpoError:
            # SDK/provider exceptions can contain submitted MT5 credentials.
            logger.error("Tonpo registration failed for %s; provider error redacted", telegram_id)
            self.user_clients.pop(telegram_id, None)
            self.user_api_keys.pop(telegram_id, None)
            self.user_gateway_ids.pop(telegram_id, None)
            return False, "Tonpo registration failed", {}
        except Exception:
            logger.error("Unexpected Tonpo registration error for %s; provider error redacted", telegram_id)
            self.user_clients.pop(telegram_id, None)
            self.user_api_keys.pop(telegram_id, None)
            self.user_gateway_ids.pop(telegram_id, None)
            return False, "Tonpo registration failed", {}
        finally:
            self._registration_inflight.discard(telegram_id)

    # ── Connection access ─────────────────────────────────────────────────────

    async def get_connection(self, telegram_id: int) -> TonpoConnectionAdapter:
        """
        Return a TonpoConnectionAdapter for the given user.
        The SDK client is created lazily — once per user, reused thereafter.
        """
        if telegram_id in self.connections:
            return self.connections[telegram_id]

        if telegram_id not in self.user_api_keys:
            raise ValueError(f"User {telegram_id} not registered with gateway")

        # Create and start SDK client if not already alive
        if telegram_id not in self.user_clients:
            api_key = self.user_api_keys[telegram_id]
            client = TonpoClient.for_user(self.gateway_config, api_key)
            try:
                await client.__aenter__()
            except Exception as exc:
                logger.error('Gateway connection failed for user %s (%s)', telegram_id, type(exc).__name__)
                raise RuntimeError('Gateway connection failed') from None
            self.user_clients[telegram_id] = client

        connection = TonpoConnectionAdapter(
            self.user_clients[telegram_id],
            self.user_account_ids.get(telegram_id, ""),
        )
        self.connections[telegram_id] = connection
        logger.info(f"Created tonpo connection for user {telegram_id}")
        return connection

    async def close_connection(self, telegram_id: int):
        """Close a user's connection and release the SDK client."""
        if telegram_id in self.connections:
            await self.connections.pop(telegram_id).close()

        if telegram_id in self.user_clients:
            try:
                await self.user_clients.pop(telegram_id).__aexit__(None, None, None)
            except Exception:
                pass

        logger.info(f"Closed tonpo connection for user {telegram_id}")

    def get_connection_status(self, telegram_id: int) -> bool:
        return telegram_id in self.connections

    def load_user_credentials(
        self,
        telegram_id:        int,
        api_key:            str,
        gateway_account_id: str,
    ):
        """
        Restore credentials from the database on bot startup.
        The SDK client is created lazily on first get_connection() call.
        """
        self.user_api_keys[telegram_id]    = api_key
        self.user_account_ids[telegram_id] = gateway_account_id


# ---------------------------------------------------------------------------
# ExecutionProvider
# ---------------------------------------------------------------------------
# Thin wrapper used by main.py — unchanged public interface.

class ExecutionProvider:
    def __init__(self, use_gateway: bool = True):
        self.use_gateway              = use_gateway
        self.gateway_manager: Optional[GatewayManager] = None

    async def initialize(self, tonpo_config: Optional[TonpoConfig] = None):
        self.gateway_manager = GatewayManager(tonpo_config)
        await self.gateway_manager.start()

    async def shutdown(self):
        if self.gateway_manager:
            await self.gateway_manager.stop()

    async def health_check(self) -> bool:
        if not self.gateway_manager:
            return False
        try:
            async with TonpoClient.admin(self.gateway_manager.gateway_config) as client:
                return await client.health_check()
        except Exception:
            return False

    async def get_connection(self, user_id: int) -> TonpoConnectionAdapter:
        if not self.gateway_manager:
            raise RuntimeError("Gateway not initialised")
        return await self.gateway_manager.get_connection(user_id)

    async def register_user(
        self,
        telegram_id:  int,
        mt5_account:  str,
        mt5_password: str,
        mt5_server:   str,
    ) -> tuple:
        if not self.gateway_manager:
            return False, "Gateway not initialised", {}
        try:
            return await self.gateway_manager.register_user(
                telegram_id, mt5_account, mt5_password, mt5_server
            )
        except Exception as exc:
            logger.error('Registration failed for %s (%s)', telegram_id, type(exc).__name__)
            return False, 'Gateway registration failed', {}
