# fx/services/payment.py
# This module handles user upgrades via crypto payments.
# 
# IMPORTANT: Blockchain detection is handled by Billing service.
# This module ONLY:
# 1. Creates payment requests in Billing
# 2. Polls Billing for payment status
# 3. Notifies users based on status
# 4. Never touches blockchain directly!

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from dataclasses import dataclass
from enum import Enum
import uuid
from decimal import Decimal, ROUND_DOWN
import secrets
import hashlib
import hmac
import json

import aiohttp
from sqlalchemy import Column, String, Integer, DateTime, Enum as SQLEnum
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.exc import IntegrityError

from config.settings import settings
from database.models import PaymentRequest as DatabasePaymentRequest, User, AdminRole, AdminAuditLog
from database.repositories import UserRepository

Base = declarative_base()
logger = logging.getLogger(__name__)

# Domain Models
class PaymentStatus(str, Enum):
    """Payment status - mirrors Billing service states"""
    PENDING = "pending"        # Created, waiting for user to send crypto
    CONFIRMED = "confirmed"    # TX detected on blockchain, confirming
    ACTIVATED = "activated"    # Enough confirmations, subscription upgraded
    EXPIRED = "expired"        # Crypto window (2h) elapsed with no TX
    FAILED = "failed"          # Payment failed (wrong amount, etc)


class PaymentMethod(str, Enum):
    """Crypto payment methods"""
    USDT_ERC20 = "usdt_erc20"  # USDT on Ethereum
    BTC = "btc"                # Bitcoin


@dataclass
class CryptoCheckoutResponse:
    """Response from POST /checkout/crypto"""
    payment_id: str
    address: str
    amount: str          # e.g., "29.900347"
    currency: str        # "USDT" or "BTC"
    expires_at: str      # ISO 8601 datetime
    expires_minutes: int


@dataclass
class PaymentStatusResponse:
    """Response from GET /payments/:id/status"""
    payment_id: str
    status: PaymentStatus
    confirmations: int = 0
    tx_hash: Optional[str] = None
    confirmed_at: Optional[str] = None
    expires_at: Optional[str] = None


class PaymentRequest(Base):
    """Local record of payment request (for tracking in Bot DB)"""
    __tablename__ = "payment_requests"
    
    id = Column(String, primary_key=True)               # UUID
    payment_id = Column(String, unique=True, index=True) # Billing's payment_id
    user_id = Column(String, index=True)                # Telegram user_id
    plan_id = Column(String)                            # 'pro', 'basic', etc
    amount_usd = Column(Integer)                        # In cents (e.g., 2990 = $29.90)
    crypto_amount = Column(String)                      # "29.900347"
    crypto_currency = Column(String)                    # "USDT" or "BTC"
    address = Column(String)                            # Wallet address
    status = Column(SQLEnum(PaymentStatus))             # Current status
    expires_at = Column(DateTime)                       # When this request expires
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

# Billing Service Client
class BillingClient:
    """HTTP client for Billing service - handles all payment operations"""
    
    def __init__(self, billing_url: str, api_key: str, timeout: int = 10):
        """
        Initialize Billing client.
        
        Args:
            billing_url: Base URL of Billing service (e.g., https://billing.tonpo.io)
            api_key: API key for authentication (X-API-Key header)
            timeout: Request timeout in seconds
        """
        self.billing_url = billing_url.rstrip('/')
        self.api_key = api_key
        self.timeout = aiohttp.ClientTimeout(total=timeout)
    
    async def _request(
        self,
        method: str,
        endpoint: str,
        json_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Make authenticated request to Billing service"""
        url = f"{self.billing_url}{endpoint}"
        headers = {"X-API-Key": self.api_key}
        
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            async with session.request(method, url, json=json_data, headers=headers) as resp:
                if resp.status != 200:
                    error_body = await resp.text()
                    raise Exception(f"Billing API error {resp.status}: {error_body}")
                
                return await resp.json()
    
    async def create_crypto_payment(
        self,
        user_id: str,
        plan_id: str,
        method: PaymentMethod
    ) -> CryptoCheckoutResponse:
        """
        POST /checkout/crypto
        
        Create a crypto payment request.
        Billing will generate unique amount and return payment details.
        
        Args:
            user_id: Telegram user ID
            plan_id: Plan to upgrade to ('pro', 'basic', etc)
            method: PaymentMethod.USDT_ERC20 or PaymentMethod.BTC
        
        Returns:
            CryptoCheckoutResponse with payment details
        """
        logger.info(f"Creating crypto checkout: user={user_id}, plan={plan_id}, method={method}")
        
        response = await self._request(
            "POST",
            "/checkout/crypto",
            {
                "user_id": user_id,
                "plan_id": plan_id,
                "method": method.value
            }
        )
        
        return CryptoCheckoutResponse(
            payment_id=response["payment_id"],
            address=response["address"],
            amount=response["amount"],
            currency=response["currency"],
            expires_at=response["expires_at"],
            expires_minutes=response["expires_minutes"]
        )
    
    async def get_payment_status(self, payment_id: str) -> PaymentStatusResponse:
        """
        GET /payments/:id/status
        
        Poll current payment status from Billing.
        Billing updates this automatically when blockchain confirms.
        
        Args:
            payment_id: Payment ID from Billing
        
        Returns:
            PaymentStatusResponse with current status
        """
        response = await self._request("GET", f"/payments/{payment_id}/status")
        
        return PaymentStatusResponse(
            payment_id=response["payment_id"],
            status=PaymentStatus(response["status"]),
            confirmations=response.get("confirmations", 0),
            tx_hash=response.get("tx_hash"),
            confirmed_at=response.get("confirmed_at"),
            expires_at=response.get("expires_at")
        )

# Payment Manager - Handles User Upgrade Flow
class PaymentManager:
    """Orchestrates crypto payment flow - pure routing + polling"""
    
    def __init__(self, billing_client: BillingClient, db_session):
        """
        Args:
            billing_client: BillingClient instance
            db_session: SQLAlchemy session for local DB
        """
        self.billing = billing_client
        self.db = db_session
    
    async def initiate_upgrade(
        self,
        user_id: str,
        plan_id: str,
        method: PaymentMethod = PaymentMethod.USDT_ERC20
    ) -> CryptoCheckoutResponse:
        """
        Step 1: User clicks "Upgrade to Pro"
        
        Create crypto payment request in Billing and return payment details.
        
        Args:
            user_id: Telegram user ID
            plan_id: Target plan ('pro', 'basic', etc)
            method: Payment method (USDT or BTC)
        
        Returns:
            Payment details to show to user (address, amount, expires_at)
        """
        logger.info(f"Initiating upgrade: user={user_id} → {plan_id}")
        
        # Call Billing to create payment
        checkout = await self.billing.create_crypto_payment(user_id, plan_id, method)
        
        # Store in local DB for tracking
        payment_record = PaymentRequest(
            id=str(uuid.uuid4()),
            payment_id=checkout.payment_id,      # Billing's ID
            user_id=user_id,
            plan_id=plan_id,
            crypto_amount=checkout.amount,
            crypto_currency=checkout.currency,
            address=checkout.address,
            status=PaymentStatus.PENDING,
            expires_at=datetime.fromisoformat(checkout.expires_at.replace('Z', '+00:00'))
        )
        self.db.add(payment_record)
        self.db.commit()
        
        logger.info(f"Payment created: {checkout.payment_id}, expires in {checkout.expires_minutes}m")
        
        return checkout
    
    async def monitor_payment(
        self,
        payment_id: str,
        user_id: str,
        notification_callback
    ) -> bool:
        """
        Step 2: Monitor payment status (polling)
        
        Poll Billing's /payments/:id/status endpoint until payment completes.
        Billing's background job handles blockchain detection automatically.
        
        This function just asks Billing: "Is it done yet?"
        
        Args:
            payment_id: Payment ID from Billing
            user_id: Telegram user ID (for logging)
            notification_callback: async function(status, confirmations, message)
        
        Returns:
            True if payment activated, False if expired/failed
        """
        logger.info(f"Monitoring payment {payment_id} for user {user_id}")
        
        max_polls = 120  # 2 hours (120 * 60 sec = 2 hours, polling every 60 sec)
        poll_count = 0
        last_confirmations = 0
        
        while poll_count < max_polls:
            try:
                # Ask Billing: What's the status?
                status = await self.billing.get_payment_status(payment_id)
                
                # Update local DB
                self._update_payment_status(payment_id, status.status)

                # Handle Status Changes
                if status.status == PaymentStatus.PENDING:
                    # Still waiting for user to send crypto
                    message = "⏳ Waiting for payment..."
                    await notification_callback(
                        status=status.status,
                        confirmations=0,
                        message=message
                    )
                
                elif status.status == PaymentStatus.CONFIRMED:
                    # Blockchain found the TX! Counting confirmations.
                    confirmations = status.confirmations or 0
                    
                    # Only notify on confirmation change
                    if confirmations != last_confirmations:
                        message = f"⏳ Payment detected! {confirmations}/12 confirmations"
                        await notification_callback(
                            status=status.status,
                            confirmations=confirmations,
                            message=message
                        )
                        last_confirmations = confirmations
                    
                    # Keep polling until 12 confirmations
                    await asyncio.sleep(60)  # Poll every 60 seconds
                    poll_count += 1
                    continue
                
                elif status.status == PaymentStatus.ACTIVATED:
                    # 🎉 Payment complete! Subscription upgraded!
                    message = "✅ Pro plan activated! You can now trade with full features."
                    await notification_callback(
                        status=status.status,
                        confirmations=status.confirmations or 12,
                        message=message
                    )
                    logger.info(f"Payment {payment_id} activated for user {user_id}")
                    return True
                
                elif status.status == PaymentStatus.EXPIRED:
                    # ❌ User didn't send crypto in time
                    message = "❌ Payment window expired (2 hours). Please try again."
                    await notification_callback(
                        status=status.status,
                        confirmations=0,
                        message=message
                    )
                    logger.warning(f"Payment {payment_id} expired for user {user_id}")
                    return False
                
                elif status.status == PaymentStatus.FAILED:
                    # ❌ Payment failed (wrong amount, etc)
                    message = "❌ Payment failed. Please contact support."
                    await notification_callback(
                        status=status.status,
                        confirmations=0,
                        message=message
                    )
                    logger.error(f"Payment {payment_id} failed for user {user_id}")
                    return False
                
                # Wait before next poll
                await asyncio.sleep(60)  # Poll every 60 seconds
                poll_count += 1
            
            except Exception as e:
                logger.error("Error monitoring payment %s (%s)", payment_id, type(e).__name__)
                await notification_callback(
                    status=PaymentStatus.FAILED,
                    confirmations=0,
                    message="❌ Error checking payment status. Please try again later."
                )
                await asyncio.sleep(60)
                poll_count += 1
        
        # Timeout
        logger.warning(f"Payment {payment_id} monitoring timeout for user {user_id}")
        return False
    
    def _update_payment_status(self, payment_id: str, status: PaymentStatus) -> None:
        """Update local payment record status"""
        payment = self.db.query(PaymentRequest)\
            .filter(PaymentRequest.payment_id == payment_id)\
            .first()
        
        if payment:
            payment.status = status
            payment.updated_at = datetime.utcnow()
            self.db.commit()

# Telegram Bot Integration
class CryptoPaymentHandler:
    """Handles /upgrade command and payment flow in Telegram Bot"""
    
    def __init__(self, payment_manager: PaymentManager, telegram_client):
        """
        Args:
            payment_manager: PaymentManager instance
            telegram_client: Telegram bot client for sending messages
        """
        self.payment = payment_manager
        self.telegram = telegram_client
    
    async def handle_upgrade_command(self, user_id: str, telegram_id: str, plan_id: str = "pro"):
        """
        User runs: /upgrade
        
        Orchestrate the entire upgrade flow:
        1. Create payment in Billing
        2. Show QR code + instructions
        3. Poll for completion
        4. Notify user
        """
        try:
            # Step 1: Initiate payment
            await self.telegram.send_message(
                telegram_id,
                "🔄 Setting up payment...",
                parse_mode="Markdown"
            )

            checkout = await self.payment.initiate_upgrade(
                user_id=user_id,
                plan_id=plan_id,
                method=PaymentMethod.USDT_ERC20
            )
            
            # Step 2: Show payment instructions
            message = (
                f"💳 **Upgrade to Pro - $29.90/month**\n\n"
                f"**Send exactly:**\n"
                f"`{checkout.amount} {checkout.currency}`\n\n"
                f"**To address:**\n"
                f"`{checkout.address}`\n\n"
                f"⏰ **Expires in:** {checkout.expires_minutes} minutes\n\n"
                f"✨ **Benefits:**\n"
                f"• 5 MT5 accounts (vs 1)\n"
                f"• 10 webhooks (vs 3)\n"
                f"• 500 API req/min (vs 100)\n\n"
                f"🔗 After you send, we'll detect it automatically!\n"
                f"Check back here for confirmation."
            )
            
            await self.telegram.send_message(
                telegram_id,
                message,
                parse_mode="Markdown"
            )
            
            # Step 3: Monitor payment (polling)
            async def notify(status: PaymentStatus, confirmations: int, message: str):
                """Callback when payment status changes"""
                await self.telegram.send_message(
                    telegram_id,
                    message,
                    parse_mode="Markdown"
                )
            
            success = await self.payment.monitor_payment(
                payment_id=checkout.payment_id,
                user_id=user_id,
                notification_callback=notify
            )
            
            # Step 4: Final message
            if success:
                await self.telegram.send_message(
                    telegram_id,
                    (
                        "🎉 **Welcome to Pro!**\n\n"
                        "You can now:\n"
                        "• Create 5 MT5 accounts\n"
                        "• Set 10 webhooks\n"
                        "• 500 API requests/min\n\n"
                        "Run /balance to see your account info."
                    ),
                    parse_mode="Markdown"
                )
            
        except Exception as e:
            logger.error("Error in upgrade command for %s (%s)", user_id, type(e).__name__)
            await self.telegram.send_message(
                telegram_id,
                "❌ The upgrade could not be completed. Please try again or contact support.",
                parse_mode="Markdown"
            )


class PaymentService:
    """Authoritative local payment-request facade used by Telegram callbacks.

    This service creates pending requests only. Subscription activation must be
    driven by a trusted external verifier; a click or local state is never
    treated as proof of payment.
    """

    def __init__(self, db):
        self.db = db
        self.users = UserRepository(db)

    @staticmethod
    def _wallet(currency: str) -> tuple[str, str]:
        currency = currency.upper()
        if currency == "USDT":
            return getattr(settings, "USDT_WALLET_ADDRESS", None) or "", "ERC20"
        if currency == "BTC":
            return getattr(settings, "BTC_WALLET_ADDRESS", None) or "", "BTC"
        raise ValueError("Unsupported payment currency")

    @staticmethod
    def _is_configured_wallet(wallet: str) -> bool:
        return bool(wallet and not wallet.startswith(("0xYour", "bc1Your", "your_")))

    def _expire(self, payment: DatabasePaymentRequest) -> None:
        if payment.status in {"pending", "submitted"} and payment.expires_at <= datetime.utcnow():
            payment.status = "expired"

    def create_payment_request(self, *, user_id: int, plan_tier: str,
                               billing_period: str, currency: str) -> Dict[str, Any]:
        user = self.users.get_by_telegram_id(user_id)
        if not user or not user.is_active or user.is_banned:
            raise ValueError("Account unavailable")
        # Serialize request creation per user. Without a row lock, two
        # simultaneous clicks can both see no pending request and create two
        # payment intents for the same entitlement.
        user = self.db.query(User).filter(User.id == user.id).with_for_update().one()
        from database.models import SubscriptionPlan
        plan = self.db.query(SubscriptionPlan).filter_by(tier=plan_tier).first()
        if not plan or plan.is_free or not plan.is_active or not plan.is_visible:
            raise ValueError("Selected plan cannot be purchased")
        if billing_period not in {"monthly", "yearly"}:
            raise ValueError("Unsupported billing period")
        wallet, network = self._wallet(currency)
        if not self._is_configured_wallet(wallet):
            raise RuntimeError("Payment provider is not configured")

        pending = self.db.query(DatabasePaymentRequest).filter(
            DatabasePaymentRequest.user_id == user.id,
            DatabasePaymentRequest.plan_tier == plan_tier,
            DatabasePaymentRequest.billing_period == billing_period,
            DatabasePaymentRequest.currency == currency.upper(),
            DatabasePaymentRequest.status == "pending",
        ).order_by(DatabasePaymentRequest.created_at.desc()).first()
        if pending:
            self._expire(pending)
            if pending.status == "pending":
                self.db.commit()
                return self._out(pending)

        base = Decimal(str(plan.price_yearly if billing_period == "yearly" else plan.price_monthly))
        # The offset identifies a request; it is never payment confirmation.
        offset = Decimal(secrets.randbelow(9000) + 1000) / Decimal("100000")
        unique_amount = (base + offset).quantize(Decimal("0.0001"), rounding=ROUND_DOWN)
        payment = DatabasePaymentRequest(
            user_id=user.id,
            plan_tier=plan_tier,
            billing_period=billing_period,
            base_amount=base,
            unique_amount=unique_amount,
            currency=currency.upper(),
            wallet_address=wallet,
            network=network,
            status="pending",
            expires_at=datetime.utcnow() + timedelta(hours=getattr(settings, "PAYMENT_EXPIRY_HOURS", 2)),
        )
        self.db.add(payment)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            raise RuntimeError("Payment request could not be created")
        self.db.refresh(payment)
        return self._out(payment)

    def get_pending_payment(self, user_id: int, payment_id: str | None = None) -> Optional[Dict[str, Any]]:
        user = self.users.get_by_telegram_id(user_id)
        if not user:
            return None
        query = self.db.query(DatabasePaymentRequest).filter(
            DatabasePaymentRequest.user_id == user.id,
            DatabasePaymentRequest.status.in_(("pending", "submitted")),
        )
        if payment_id:
            query = query.filter(DatabasePaymentRequest.uuid == payment_id)
        payment = query.order_by(DatabasePaymentRequest.created_at.desc()).first()
        if not payment:
            return None
        self._expire(payment)
        self.db.commit()
        return self._out(payment) if payment.status in {"pending", "submitted"} else None

    def _cancel_pending(self, user_id: int, payment_id: str | None = None) -> bool:
        user = self.users.get_by_telegram_id(user_id)
        if not user:
            return False
        query = self.db.query(DatabasePaymentRequest).filter(
            DatabasePaymentRequest.user_id == user.id,
            DatabasePaymentRequest.status == "pending",
        )
        if payment_id:
            query = query.filter(DatabasePaymentRequest.uuid == payment_id)
        payment = query.order_by(DatabasePaymentRequest.created_at.desc()).first()
        if not payment:
            return False
        payment.status = "cancelled"
        self.db.commit()
        return True

    @staticmethod
    def _out(payment: DatabasePaymentRequest) -> Dict[str, Any]:
        return {
            "payment_id": payment.uuid,
            "plan_tier": payment.plan_tier,
            "billing_period": payment.billing_period,
            "amount": str(payment.unique_amount),
            "wallet_address": payment.wallet_address,
            "currency": payment.currency,
            "network": payment.network,
            "expires_at": payment.expires_at.isoformat(),
            "expires_in_minutes": max(0, int((payment.expires_at - datetime.utcnow()).total_seconds() // 60)),
            "status": payment.status,
            "verification": "admin_approved" if payment.status == "approved" else "manual_review",
        }

    def _admin_role(self, admin_id: int) -> str | None:
        """Return an authorized payment-review role, or None."""
        if admin_id in set(getattr(settings, "ADMIN_USER_IDS", []) or []):
            return "SUPER_ADMIN"
        role = self.db.query(AdminRole).filter(
            AdminRole.telegram_id == admin_id, AdminRole.is_active == True  # noqa: E712
        ).first()
        if not role:
            return None
        permissions = set(role.permissions or [])
        if role.role in {"ADMIN", "SUPER_ADMIN"} or "*" in permissions or "subscriptions.manage" in permissions:
            return role.role
        return None

    def _require_payment_admin(self, admin_id: int) -> str:
        role = self._admin_role(admin_id)
        if not role:
            raise PermissionError("Payment review authorization required")
        return role

    def submit_payment_proof(self, *, user_id: int, payment_id: str, tx_hash: str,
                             amount: Decimal | str, currency: str, network: str,
                             recipient: str | None = None) -> Dict[str, Any]:
        """Store untrusted user proof for manual review; never grant access."""
        user = self.users.get_by_telegram_id(user_id)
        if not user or not user.is_active or user.is_banned:
            raise ValueError("Account unavailable")
        payment = self.db.query(DatabasePaymentRequest).filter(
            DatabasePaymentRequest.uuid == payment_id,
            DatabasePaymentRequest.user_id == user.id,
        ).with_for_update().first()
        if not payment:
            raise ValueError("Payment request not found")
        self._expire(payment)
        if payment.status == "expired":
            self.db.commit()
            raise ValueError("Payment has expired")
        if payment.status == "submitted":
            if payment.tx_hash == str(tx_hash).strip():
                return self._out(payment) | {"idempotent": True}
            raise ValueError("Payment proof is already under review")
        if payment.status in {"approved", "activated", "rejected", "cancelled"}:
            raise ValueError("Payment request is not accepting proof")
        tx_hash = str(tx_hash or "").strip()
        currency = str(currency or "").upper().strip()
        network = str(network or "").upper().strip()
        if not tx_hash or len(tx_hash) > 100:
            raise ValueError("Invalid transaction hash")
        if currency != payment.currency or network != payment.network:
            raise ValueError("Payment currency or network mismatch")
        if recipient is not None and str(recipient).strip() != payment.wallet_address:
            raise ValueError("Payment recipient mismatch")
        try:
            submitted_amount = Decimal(str(amount))
        except Exception as exc:
            raise ValueError("Invalid payment amount") from exc
        if submitted_amount != Decimal(str(payment.unique_amount)):
            raise ValueError("Payment amount mismatch")
        duplicate = self.db.query(DatabasePaymentRequest).filter(
            DatabasePaymentRequest.network == payment.network,
            DatabasePaymentRequest.tx_hash == tx_hash,
            DatabasePaymentRequest.id != payment.id,
        ).first()
        if duplicate:
            raise ValueError("Payment transaction already assigned")
        payment.tx_hash = tx_hash
        payment.confirmed_amount = submitted_amount
        payment.proof_submitted_at = datetime.utcnow()
        payment.status = "submitted"
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise ValueError("Payment transaction already assigned") from exc
        return self._out(payment) | {"idempotent": False}

    def approve_payment(self, *, payment_id: str, admin_id: int) -> Dict[str, Any]:
        """Atomically approve one submitted proof and activate its subscription."""
        role = self._require_payment_admin(admin_id)
        payment = self.db.query(DatabasePaymentRequest).filter(
            DatabasePaymentRequest.uuid == payment_id
        ).with_for_update().first()
        if not payment:
            raise ValueError("Payment request not found")
        self._expire(payment)
        if payment.status == "expired":
            self.db.commit()
            raise ValueError("Payment has expired")
        if payment.status == "approved":
            return self._out(payment) | {"status": "approved", "idempotent": True}
        if payment.status in {"rejected", "cancelled", "pending"}:
            raise ValueError("Payment proof is not ready for approval")
        if payment.status != "submitted" or not payment.tx_hash:
            raise ValueError("Payment proof is not ready for approval")
        if payment.confirmed_amount != Decimal(str(payment.unique_amount)):
            raise ValueError("Payment amount mismatch")
        configured_wallet, configured_network = self._wallet(payment.currency)
        if (not self._is_configured_wallet(configured_wallet)
                or payment.wallet_address != configured_wallet
                or payment.network != configured_network):
            raise ValueError("Payment recipient or network is no longer configured")
        duplicate = self.db.query(DatabasePaymentRequest).filter(
            DatabasePaymentRequest.network == payment.network,
            DatabasePaymentRequest.tx_hash == payment.tx_hash,
            DatabasePaymentRequest.id != payment.id,
        ).first()
        if duplicate:
            raise ValueError("Payment transaction already assigned")
        user = self.db.query(User).filter(User.id == payment.user_id).with_for_update().one()
        from database.models import SubscriptionPlan
        plan = self.db.query(SubscriptionPlan).filter_by(tier=payment.plan_tier).first()
        if not plan or not plan.is_active or not plan.is_visible:
            raise ValueError("Payment plan is unavailable")
        old_value = {"status": payment.status, "subscription_tier": user.subscription_tier}
        duration = 365 if payment.billing_period == "yearly" else 30
        user.subscription_tier = payment.plan_tier
        user.subscription_expiry = datetime.utcnow() + timedelta(days=duration)
        user.subscription_features = {
            "max_trades": plan.max_trades_per_day,
            "max_position_size": float(plan.max_position_size),
            "max_symbols": plan.max_symbols,
            "multiple_tps": plan.supports_multiple_tps,
            "auto_trading": plan.supports_auto_trading,
            "api_access": plan.supports_api,
            "max_connections": plan.max_connections,
            "rate_limit": plan.rate_limit_per_second,
            "support_priority": plan.support_priority,
        }
        payment.status = "approved"
        payment.confirmed_at = payment.confirmed_at or datetime.utcnow()
        payment.activated_at = datetime.utcnow()
        payment.reviewed_at = datetime.utcnow()
        payment.reviewed_by = admin_id
        self.db.add(AdminAuditLog(
            admin_telegram_id=admin_id, role=role, action="payment_approve",
            target_type="payment", target_id=payment.uuid, old_value=old_value,
            new_value={"status": "approved", "subscription_tier": payment.plan_tier, "tx_hash": payment.tx_hash},
            result="success",
        ))
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise ValueError("Payment transaction already assigned") from exc
        return self._out(payment) | {"status": "approved", "idempotent": False}

    def reject_payment(self, *, payment_id: str, admin_id: int, reason: str) -> Dict[str, Any]:
        """Reject proof transactionally; rejected requests can never activate."""
        role = self._require_payment_admin(admin_id)
        reason = str(reason or "").strip()
        if not reason or len(reason) > 255:
            raise ValueError("A rejection reason is required")
        payment = self.db.query(DatabasePaymentRequest).filter(
            DatabasePaymentRequest.uuid == payment_id
        ).with_for_update().first()
        if not payment:
            raise ValueError("Payment request not found")
        if payment.status == "rejected":
            return self._out(payment) | {"status": "rejected", "idempotent": True}
        if payment.status in {"approved", "activated"}:
            raise ValueError("Approved payment cannot be rejected")
        if payment.status == "expired":
            raise ValueError("Expired payment cannot be reviewed")
        old_status = payment.status
        payment.status = "rejected"
        payment.reviewed_at = datetime.utcnow()
        payment.reviewed_by = admin_id
        payment.rejection_reason = reason
        self.db.add(AdminAuditLog(
            admin_telegram_id=admin_id, role=role, action="payment_reject",
            target_type="payment", target_id=payment.uuid,
            old_value={"status": old_status}, new_value={"status": "rejected", "reason": reason},
            result="success",
        ))
        self.db.commit()
        return self._out(payment) | {"status": "rejected", "idempotent": False}

    @staticmethod
    def verify_webhook_signature(raw_body: bytes, signature: Optional[str]) -> bool:
        """Verify the generic provider boundary without exposing the secret."""
        configured = getattr(settings, "PAYMENT_WEBHOOK_SECRET", None)
        if not configured or not signature:
            return False
        expected = hmac.new(
            str(configured).encode("utf-8"), raw_body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, str(signature).strip())

    def process_verified_event(self, raw_body: bytes, signature: Optional[str]) -> Dict[str, Any]:
        """Reject the obsolete automatic-provider path.

        Tonpo uses manual administrator approval. A user or webhook cannot
        activate a subscription, even when a payload is signed.
        """
        raise PermissionError("Automatic payment verification is disabled; admin approval is required")
