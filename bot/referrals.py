"""Telegram referral deep-link helpers."""

from __future__ import annotations

import re


REFERRAL_FEATURE_KEY = "referral_attribution"
_REFERRAL_PAYLOAD = re.compile(r"^ref_(\d{1,20})$")


def parse_referral_payload(args, referred_telegram_id: int) -> int | None:
    """Return the referring Telegram ID from /start payload, rejecting self-referrals."""
    if not args:
        return None
    match = _REFERRAL_PAYLOAD.fullmatch(str(args[0]))
    if not match:
        return None
    referrer_id = int(match.group(1))
    if referrer_id <= 0 or referrer_id == int(referred_telegram_id):
        return None
    return referrer_id


async def build_referral_link(bot, telegram_id: int) -> str:
    """Build a Telegram deep link from the bot identity returned by Telegram."""
    bot_user = await bot.get_me()
    username = getattr(bot_user, "username", None)
    if not username:
        raise ValueError("Telegram did not return a bot username")
    return f"https://t.me/{username}?start=ref_{int(telegram_id)}"


def add_referral_attribution(
    subscription_features: dict | None,
    referrer_telegram_id: int | None,
    referred_telegram_id: int,
) -> dict:
    """Add first-time attribution while preserving existing feature and referral data."""
    features = dict(subscription_features or {})
    if features.get(REFERRAL_FEATURE_KEY):
        return features
    if referrer_telegram_id is None:
        return features
    if int(referrer_telegram_id) <= 0 or int(referrer_telegram_id) == int(referred_telegram_id):
        return features
    features[REFERRAL_FEATURE_KEY] = {
        "referrer_telegram_id": int(referrer_telegram_id),
    }
    return features
