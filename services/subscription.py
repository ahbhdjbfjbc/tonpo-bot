# fx/services/subscription.py
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Tuple
import logging
from types import SimpleNamespace
from sqlalchemy.orm import Session

from database.models import User, SubscriptionPlan
from database.repositories import UserRepository
from config.settings import settings
from core.exceptions import SubscriptionError

logger = logging.getLogger(__name__)

DEFAULT_TRIAL_DAYS = 3

class SubscriptionService:
    """
    Manages user subscriptions and plan limits
    """
    
    def __init__(self, db_session: Session):
        self.db = db_session
        self.user_repo = UserRepository(db_session)
        self._plans_cache = None
        self._plans_cache_time = None
    
    def get_plan(self, tier: str) -> Optional[SubscriptionPlan]:
        """Get subscription plan by tier"""
        return self.db.query(SubscriptionPlan).filter(
            SubscriptionPlan.tier == tier
        ).first()

    def get_purchase_plan(self, tier: str) -> Optional[SubscriptionPlan]:
        """Only active and visible plans can be newly purchased."""
        plan = self.get_plan(tier)
        return plan if plan and plan.is_active and plan.is_visible else None
    
    def get_all_plans(self, refresh: bool = False) -> List[SubscriptionPlan]:
        """Get all subscription plans with caching"""
        # Cache for 1 hour
        if (not self._plans_cache or refresh or 
            not self._plans_cache_time or 
            datetime.utcnow() - self._plans_cache_time > timedelta(hours=1)):
            
            self._plans_cache = [plan for plan in self.db.query(SubscriptionPlan).all()
                                 if plan.is_active and plan.is_visible]
            self._plans_cache_time = datetime.utcnow()
        
        return self._plans_cache
    
    def get_user_plan(self, user_id: int) -> SubscriptionPlan:
        """Get user's current subscription plan"""
        user = self.user_repo.get_by_telegram_id(user_id)
        if not user:
            raise SubscriptionError("User not found")
        
        # Check if subscription expired
        if user.subscription_expiry and user.subscription_expiry < datetime.utcnow():
            # Downgrade to free
            user.subscription_tier = 'free'
            user.subscription_expiry = None
            self.db.commit()
            logger.info(f"User {user_id} downgraded to free plan (expired)")

        # Existing subscriptions use the feature snapshot saved at purchase
        # time, so later catalog edits do not silently change paid entitlements.
        snapshot = user.subscription_features or {}
        if user.subscription_expiry and user.subscription_expiry >= datetime.utcnow() \
                and 'max_trades' in snapshot:
            return SimpleNamespace(
                tier=user.subscription_tier,
                max_trades_per_day=snapshot.get('max_trades', 10),
                max_position_size=snapshot.get('max_position_size', 1.0),
                max_symbols=snapshot.get('max_symbols', 30),
                supports_multiple_tps=snapshot.get('multiple_tps', False),
                supports_auto_trading=snapshot.get('auto_trading', False),
                supports_api=snapshot.get('api_access', False),
                support_priority=snapshot.get('support_priority', 'normal'),
                max_connections=snapshot.get('max_connections', 1),
                rate_limit_per_second=snapshot.get('rate_limit', 1),
            )
        
        plan = self.get_plan(user.subscription_tier)
        if not plan:
            logger.error(f"Plan '{user.subscription_tier}' not found for user {user_id}, falling back to free")
            
            free_plan = self.get_plan('free')
            
            if not free_plan:
            	# Create default free plan if it doesn't exist
            	from database.models import SubscriptionPlan
            	free_plan = SubscriptionPlan(
            	    tier='free',
            	    name='Free',
            	    price_monthly=0,
            	    price_yearly=0,
            	    max_trades_per_day=10,
            	    max_position_size=1.0,
            	    max_symbols=30,
            	    supports_multiple_tps=False,
            	    supports_auto_trading=False,
            	    supports_api=False,
            	    support_priority='low',
            	    max_connections=1
            	)
            	self.db.add(free_plan)
            	self.db.commit()
            	
            # plan = self.get_plan('free')
            user.subscription_tier = 'free'
            self.db.commit()
            return free_plan
        
        return plan
    
    def check_trade_limit(self, user_id: int) -> Tuple[bool, Dict[str, Any]]:
        """Check if user has exceeded daily trade limit"""
        user = self.user_repo.get_by_telegram_id(user_id)
        if not user:
            return False, {"error": "User not found"}
        
        plan = self.get_user_plan(user_id)
        
        # Reset daily counter if new day
        if user.last_trade_date and user.last_trade_date.date() < datetime.utcnow().date():
            user.daily_trades = 0
            self.db.commit()
        
        # Check limit
        if user.daily_trades >= plan.max_trades_per_day:
            return False, {
                "limited": True,
                "current": user.daily_trades,
                "limit": plan.max_trades_per_day,
                "plan": plan.tier,
                "reset": datetime.utcnow().replace(hour=0, minute=0, second=0) + timedelta(days=1)
            }
        
        return True, {
            "limited": False,
            "current": user.daily_trades,
            "limit": plan.max_trades_per_day,
            "remaining": plan.max_trades_per_day - user.daily_trades
        }
    
    def check_position_size_limit(self, user_id: int, requested_size: float) -> Tuple[bool, str]:
        """Check if requested position size is within plan limits"""
        plan = self.get_user_plan(user_id)
        
        if requested_size > plan.max_position_size:
            return False, (f"Position size {requested_size} exceeds plan limit "
                          f"{plan.max_position_size}. Upgrade to increase limit.")
        
        return True, "OK"
    
    def check_symbol_limit(self, user_id: int, current_symbols: int) -> Tuple[bool, str]:
    	"""Check if user can subscribe to more symbols"""
    	plan = self.get_user_plan(user_id)
    	
    	if plan.max_symbols == 0:
    		# 0 = unlimited
    		return True, "OK"
    	
    	if current_symbols >= plan.max_symbols:
    		return False, (
    		    f"Symbol limit reached ({plan.max_symbols} for {plan.tier} plan). "
    		    "Upgrade to add more symbols."
    		)
    	return True, "OK"
                          
    	
    def check_feature_access(self, user_id: int, feature: str) -> bool:
        """Check if user has access to a specific feature"""
        plan = self.get_user_plan(user_id)
        
        feature_map = {
            'multiple_tps': plan.supports_multiple_tps,
            'auto_trading': plan.supports_auto_trading,
            'api_access': plan.supports_api,
            'priority_support': plan.support_priority == 'high'
        }
        
        return feature_map.get(feature, False)
    
    def increment_trade_count(self, user_id: int):
        """Increment user's daily trade count"""
        user = self.user_repo.get_by_telegram_id(user_id)
        if user:
            user.daily_trades += 1
            user.total_trades += 1
            user.last_trade_date = datetime.utcnow()
            self.db.commit()
    
    def upgrade_user(self, user_id: int, plan_tier: str,
                    billing_period: str = 'monthly',
                    payment_method: str = 'crypto',
                    payment_id: str = '',
                    tx_hash: str = '') -> Dict[str, Any]:
        """Deprecated user-facing activation path; admin approval is required."""
        user = self.user_repo.get_by_telegram_id(user_id)
        if not user:
            raise SubscriptionError("User not found")
        raise SubscriptionError("Subscription activation is admin-controlled")

    def downgrade_user(self, user_id: int, reason: str = "expired") -> Dict[str, Any]:
        """Downgrade user to free plan"""
        user = self.user_repo.get_by_telegram_id(user_id)
        if not user:
            raise SubscriptionError("User not found")
        
        old_plan = user.subscription_tier
        user.subscription_tier = 'free'
        user.subscription_expiry = None
        
        self.db.commit()
        
        referral_attribution = (user.subscription_features or {}).get('referral_attribution')
        user.subscription_features = {
            'max_trades': 10,
            'max_position_size': 1.0,
            'max_symbols': 10,
            'multiple_tps': False,
            'auto_trading': False,
            'api_access': False,
            'max_connections': 1,
            'rate_limit': 1
        }
        if referral_attribution:
            user.subscription_features['referral_attribution'] = referral_attribution
        
        logger.info(f"User {user_id} downgraded from {old_plan} to free: {reason}")
        
        return {
            'success': True,
            'user_id': user_id,
            'old_plan': old_plan,
            'new_plan': 'free',
            'reason': reason
        }
    
    def get_expiring_soon(self, days: int = 7) -> List[Tuple[User, int]]:
        """Get users whose subscriptions expire soon"""
        cutoff = datetime.utcnow() + timedelta(days=days)
        
        users = self.db.query(User).filter(
            User.subscription_tier != 'free',
            User.subscription_expiry <= cutoff,
            User.subscription_expiry > datetime.utcnow()
        ).all()
        
        result = []
        for user in users:
            days_left = (user.subscription_expiry - datetime.utcnow()).days
            result.append((user, days_left))
        
        return result
    
    def get_expired(self) -> List[User]:
        """Get users with expired subscriptions"""
        return self.db.query(User).filter(
            User.subscription_tier != 'free',
            User.subscription_expiry < datetime.utcnow()
        ).all()
    
    def process_expired(self, notification_service=None) -> int:
    	"""Process all expired subscriptions, downgrade to free, and notify users"""
    	expired = self.get_expired()
    	count = 0
    	
    	for user in expired:
    		try:
    			old_plan = user.subscription_tier
    			self.downgrade_user(user.telegram_id, "expired")
    			count += 1
    			
    			# Send notification if service is available
    			if notification_service:
    				import asyncio
    				try:
    					try:
    						loop = asyncio.get_running_loop()
    					except RuntimeError:
    						loop = None
    					if loop is not None:
    						asyncio.ensure_future(
    						    notification_service.send_telegram(
    						        user.telegram_id,
    						        notification_service.templates['subscription_expired'].format(
    						            plan=old_plan
    						        )
    						    )
    						)
    					else:
    						asyncio.run(
    						    notification_service.send_telegram(
    						        user.telegram_id,
    						        notification_service.templates['subscription_expired'].format(
    						            plan=old_plan
    						        )
    						    )
    						)
    				except Exception as notify_err:
    					logger.error(f"Failed to notify user {user.telegram_id} of expiry: {notify_err}")
    		except Exception as e:
                    logger.error("Failed to downgrade user %s (%s)", user.telegram_id, type(e).__name__)
    	
    	return count
    
    def get_usage_stats(self, user_id: int) -> Dict[str, Any]:
    	"""Get usage statistics for user"""
    	user = self.user_repo.get_by_telegram_id(user_id)
    	
    	if not user:
    		raise SubscriptionError("User not found")
    	
    	plan = self.get_user_plan(user_id)
    	
    	if plan is None:
    		# Log this unexpected situation
    		logger.error(f"User {user_id} has no valid plan, using default stats")
    		
    		return {
    		    'plan': 'unknown',
    		    'expiry': None,
    		    'trades_today': user.daily_trades,
    		    'trade_limit': 0,
    		    'trade_usage_percent': 0,
    		    'total_trades': user.total_trades,
    		    'total_volume': user.total_volume,
    		    'features': {
    		        'multiple_tps': False,
    		        'auto_trading': False,
    		        'api_access': False
    		    }
    		}
    	
    	# Calculate usage percentages
    	trade_usage = (user.daily_trades / plan.max_trades_per_day * 100) if plan and plan.max_trades_per_day > 0 else 0
    	
    	return {
            'plan': plan.tier,
            'expiry': user.subscription_expiry.isoformat() if user.subscription_expiry else None,
            'trades_today': user.daily_trades,
            'trade_limit': plan.max_trades_per_day,
            'trade_usage_percent': round(trade_usage, 1),
            'total_trades': user.total_trades,
            'total_volume': user.total_volume,
            'features': {
                'multiple_tps': plan.supports_multiple_tps,
                'auto_trading': plan.supports_auto_trading,
                'api_access': plan.supports_api
            }
        }
    
    def get_plan_features(self, tier: str) -> Dict[str, Any]:
        """Get feature list for a plan"""
        plan = self.get_plan(tier)
        if not plan:
            return {}
        
        return {
            'name': plan.name,
            'tier': plan.tier,
            'price_monthly': float(plan.price_monthly),
            'price_yearly': float(plan.price_yearly),
            'max_trades_per_day': plan.max_trades_per_day,
            'max_position_size': plan.max_position_size,
            'max_symbols': plan.max_symbols,
            'supports_multiple_tps': plan.supports_multiple_tps,
            'supports_auto_trading': plan.supports_auto_trading,
            'supports_api': plan.supports_api,
            'support_priority': plan.support_priority,
            'max_connections': plan.max_connections,
            'is_active': plan.is_active,
            'is_visible': plan.is_visible,
            'trial_eligible': plan.trial_eligible,
            'display_order': plan.display_order,
            'features': plan.features or []
        }

    def public_plan_catalog(self) -> List[Dict[str, Any]]:
        """Return active, visible plan metadata without payment secrets."""
        plans = sorted(self.get_all_plans(), key=lambda item: item.display_order)
        return [self.get_plan_features(plan.tier) for plan in plans]


class TrialService:
    """
    Manages free trials for new users
    """
    
    def __init__(self, db_session: Session):
        self.db = db_session
        self.sub_service = SubscriptionService(db_session)
    
    def start_trial(self, user_id: int, days: int = DEFAULT_TRIAL_DAYS) -> Dict[str, Any]:
        """Start a free trial for a user"""
        # Lock the authoritative user row so two concurrent requests cannot
        # both observe trial_used=False and grant two trials.
        user = self.db.query(User).filter(User.telegram_id == user_id).with_for_update().first()
        if not user:
            raise SubscriptionError("User not found")
        
        # Check if user already had a trial
        if user.trial_used:
            return {
                'success': False,
                'message': 'Trial already used'
            }
        
        # Set trial plan
        user.subscription_tier = 'pro'  # Give them pro features
        user.subscription_expiry = datetime.utcnow() + timedelta(days=days)
        user.trial_used = True
        user.trial_start = datetime.utcnow()
        user.trial_end = datetime.utcnow() + timedelta(days=days)
        
        self.db.commit()
        
        logger.info(f"User {user_id} started {days}-day trial")
        
        return {
            'success': True,
            'message': f'Trial started for {days} days',
            'expiry': user.subscription_expiry.isoformat(),
            'features': self.sub_service.get_plan_features('pro')
        }
    
    def get_trial_status(self, user_id: int) -> Dict[str, Any]:
        """Return server-authoritative, timezone-naive UTC trial state."""
        user = self.db.query(User).filter(User.telegram_id == user_id).first()
        if not user:
            return {"status": "UNAVAILABLE", "active": False, "remaining_seconds": 0}
        now = datetime.utcnow()
        if not user.trial_used or not user.trial_end:
            return {"status": "NOT_STARTED", "active": False, "remaining_seconds": 0, "ends_at": None}
        remaining = max(0, int((user.trial_end - now).total_seconds()))
        active = remaining > 0
        return {
            "status": "ACTIVE" if active else "EXPIRED",
            "active": active,
            "remaining_seconds": remaining,
            "remaining_days": round(remaining / 86400, 2),
            "started_at": user.trial_start.isoformat() if user.trial_start else None,
            "ends_at": user.trial_end.isoformat(),
            "trial_days": DEFAULT_TRIAL_DAYS,
        }

    def check_trial_eligibility(self, user_id: int) -> Dict[str, Any]:
        """Check if user is eligible for a trial"""
        user = self.db.query(User).filter(User.telegram_id == user_id).first()
        if not user:
            return {'eligible': False, 'reason': 'User not found'}
        
        if user.trial_used:
            return {'eligible': False, 'reason': 'Trial already used'}
        
        # Check account age (optional)
        account_age = datetime.utcnow() - user.created_at
        if account_age.days > 30:
            return {'eligible': False, 'reason': 'Account too old for trial'}
        
        return {
            'eligible': True,
            'trial_days': DEFAULT_TRIAL_DAYS,
            'features': self.sub_service.get_plan_features('pro')
        }
