"""Tonpo AI Assistant — educational guide only. Never executes trades or touches Gateway."""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from config.settings import settings
from database.models import SignalReceipt, Trade, User
from services.results import ResultsService
from services.subscription import SubscriptionService, TrialService
from services.news_protection import NewsProtectionService

# Knowledge answers (bilingual). No secrets, no promises of profit.
KB: Dict[str, Dict[str, str]] = {
    "demo": {
        "ar": "وضع DEMO (تجريبي): إعداد لحسابك يعني أنك تختار بيئة تجريبية. حتى في LIVE، إذا كان TRADING_DRY_RUN مفعّلاً على الخادم فلن تُرسل أوامر حقيقية. لتغيير الوضع استخدم واجهة المنصة (Trading Mode) وليس المساعد.",
        "en": "DEMO mode is your per-account simulation preference. Even if you select LIVE, real broker orders stay blocked while the server TRADING_DRY_RUN flag is on. To change mode, use the Web Trading Mode control — not this assistant.",
    },
    "live_mode": {
        "ar": "وضع LIVE: تفضيل حسابك للتداول الحقيقي عندما تسمح بيئة الخادم. المساعد لا يفعّل LIVE. استخدم زر Trading Mode في لوحة الويب مع تأكيد صريح. حالياً TRADING_DRY_RUN يمنع الأوامر الحقيقية.",
        "en": "LIVE mode is your preference for real trading when the server allows it. This assistant cannot enable LIVE. Use the Web Trading Mode control with explicit confirmation. TRADING_DRY_RUN currently blocks real orders.",
    },

    "register": {
        "ar": "للتسجيل: افتح بوت تليجرام واكتب /start ثم /register. أدخل بيانات حساب MT5 عبر البوت فقط. لا تشارك كلمة مرور MT5 في المحادثة هنا.",
        "en": "To register: open the Telegram bot, send /start then /register. Enter MT5 account details only through the bot. Never share your MT5 password here.",
    },
    "login": {
        "ar": "لتسجيل الدخول إلى المنصة: استخدم Telegram ID ومفتاح API من إعدادات البوت (الأمر /settings أو قسم API داخل البوت).",
        "en": "To log in: use your Telegram ID and the API key from the bot settings (/settings or the API section in the bot).",
    },
    "mt5": {
        "ar": "لربط MT5: عبر بوت تليجرام أكمل التسجيل وأدخل حساب البوابة (Gateway). المنصة تعرض حالة الاتصال فقط ولا تخزّن كلمة المرور في الواجهة.",
        "en": "To connect MT5: complete registration in the Telegram bot and enter gateway credentials. The web UI only shows connection status and never stores passwords in the browser.",
    },
    "subscription": {
        "ar": "لتفعيل الاشتراك: من البوت استخدم /upgrade أو قسم الباقات. بعد الدفع تُحدَّث خطتك تلقائياً. المنصة تعرض خطتك الحالية في الإعدادات.",
        "en": "To activate a subscription: use /upgrade in the bot or the plans section. After payment your plan updates automatically. The web UI shows your current plan under Settings.",
    },
    "trading": {
        "ar": "لبدء التداول: 1) سجّل وربط MT5 2) فعّل الاشتراك المناسب 3) اضبط المخاطرة 4) اربط TradingView أو انتظر إشارات القناة. التنفيذ يمر عبر SignalPipeline والمخاطر — والوضع الحالي Dry Run قد يمنع الأوامر الحقيقية.",
        "en": "To start trading: 1) Register and connect MT5 2) Activate a suitable plan 3) Set risk 4) Connect TradingView or use channel signals. Execution goes through SignalPipeline and risk checks — Dry Run mode may block real orders.",
    },
    "tradingview": {
        "ar": "لربط TradingView: أعد Webhook إلى عنوان المنصة /api/webhooks/tradingview مع الرأس السري X-TradingView-Secret، استخدم الإعداد الموثوق على الخادم مع symbol وaction وstop_loss وtake_profits. لا تُرسل user_id لتحديد مستخدم آخر.",
        "en": "To connect TradingView: point the webhook to /api/webhooks/tradingview with header X-TradingView-Secret, and include symbol, action, stop_loss, and take_profits. User identity is resolved by trusted server configuration.",
    },
    "signals": {
        "ar": "إشاراتك تظهر في صفحة «الإشارات». كل مستخدم يرى إشاراته فقط. الحالة dry_run تعني أن التنفيذ محجوب بوضع المحاكاة.",
        "en": "Your signals appear on the Signals page. Each user only sees their own. Status dry_run means execution is blocked by simulation mode.",
    },
    "not_executed": {
        "ar": "أسباب شائعة لعدم التنفيذ: TRADING_DRY_RUN=true، اشتراك لا يدعم التداول الآلي، إيقاف طارئ، إشارة مكررة، SL ناقص، أو timestamp قديم. راجع تفاصيل الإشارة وحالتها.",
        "en": "Common reasons a trade did not execute: TRADING_DRY_RUN=true, plan without auto-trading, emergency stop, duplicate signal, missing SL, or stale timestamp. Check signal details and status.",
    },
    "sl": {
        "ar": "Stop Loss (وقف الخسارة) مستوى سعري يُغلق الصفقة للحد من الخسارة. الإشارات من TradingView تتطلب SL. لا يمكن تجاوز محرك المخاطر من الواجهة.",
        "en": "Stop Loss is a price level that closes the trade to limit loss. TradingView signals require SL. The web UI cannot bypass the risk engine.",
    },
    "tp": {
        "ar": "Take Profit (جني الأرباح) مستوى سعري لإغلاق الصفقة عند ربح مستهدف. يمكن وجود عدة أهداف TP في الإشارة.",
        "en": "Take Profit is a price level to close the trade at a target profit. Signals may include multiple TP levels.",
    },
    "risk": {
        "ar": "إدارة المخاطر تحدد نسبة المخاطرة لكل صفقة والحدود اليومية. عدّلها من الإعدادات بعد الحفظ عبر API المصرح به فقط.",
        "en": "Risk settings define per-trade risk and daily limits. Update them from Settings via the authenticated API only.",
    },
    "welcome": {
        "ar": "أهلًا بك في Tonpo — حماية وتنفيذ آمن للإشارات. ابدأ بالتسجيل، اربط MT5، راجع المخاطر، ثم راقب إشاراتك ونتائجك من لوحة التحكم. تحصل الحسابات الجديدة المؤهلة على تجربة مجانية 3 أيام. المساعد هنا للإرشاد فقط.",
        "en": "Welcome to Tonpo — protected signal validation and execution. Register, connect MT5, review risk, then follow signals and real results from your dashboard. Eligible new accounts receive a 3-day free trial. This assistant is guidance only.",
    },
    "account": {
        "ar": "أستطيع عرض حالة الحساب الحالية فقط: التسجيل، اتصال MT5، التجربة، الاشتراك، وآخر قرارات الإشارات. افتح Account أو استخدم /account.",
        "en": "I can explain your current account state: registration, MT5 connection, trial, subscription, and recent signal decisions. Open Account or use /account.",
    },
    "trial": {
        "ar": "التجربة المجانية مدتها 3 أيام وتبدأ مرة واحدة من الخادم عند إنشاء الحساب المؤهل. بعد انتهائها لا يمكن إعادة تشغيلها؛ راجع الباقات للاشتراك.",
        "en": "The free trial lasts 3 days and starts once server-side for an eligible new account. It cannot be restarted after expiry; review the available plans to subscribe.",
    },
    "results": {
        "ar": "يعرض Results Center النتائج المحفوظة فعليًا فقط. إذا لم توجد صفقة مغلقة أو بيانات، سأقول إنها غير متاحة بدل اختراع أرقام.",
        "en": "Results Center shows only persisted real results. If no closed trade or metric exists, it is reported as unavailable rather than invented.",
    },
    "news": {
        "ar": "News Protection قد تمنع الإشارة عند وجود خبر مؤثر أو عند غياب/تقادم بيانات الأخبار. القرار يأتي من backend ويظل fail-closed.",
        "en": "News Protection can block a signal for a high-impact event or when news data is stale/unavailable. The backend decides and remains fail-closed.",
    },
}


def detect_lang(text: str, preferred: Optional[str] = None) -> str:
    if preferred in ("ar", "en"):
        return preferred
    if re.search(r"[\u0600-\u06FF]", text or ""):
        return "ar"
    return "en"


def _match_intent(msg: str) -> str:
    m = (msg or "").lower()
    pairs = [
        ("welcome", ["welcome", "مرحبا", "مرحب", "ابدأ", "start"]),
        ("account", ["حسابي", "حالة حساب", "account status", "my account"]),
        ("trial", ["trial", "تجربة", "تنتهي التجربة", "free trial"]),
        ("results", ["نتيجة", "نتائج", "results", "last trade", "آخر صفقة"]),
        ("news", ["أخبار", "news", "منع التداول بسبب الأخبار"]),
        ("register", ["سجل", "تسجيل", "register", "sign up"]),
        ("login", ["دخول", "login", "sign in"]),
        ("mt5", ["mt5", "ميتا", "gateway", "بوابة", "ربط"]),
        ("subscription", ["اشتراك", "باقة", "upgrade", "subscription", "plan"]),
        ("tradingview", ["tradingview", "webhook", "ويبهوك", "ترايدنج"]),
        ("signals", ["إشار", "signal", "signals"]),
        ("not_executed", ["لم تنفذ", "لم تُنفذ", "not execute", "wasn't", "failed", "dry_run", "لماذا"]),
        ("sl", ["stop loss", "وقف", "sl"]),
        ("tp", ["take profit", "جني", "tp"]),
        ("risk", ["مخاطر", "risk"]),
        ("demo", ["demo", "تجريبي", "ديمو"]),
        ("live_mode", ["live mode", "وضع حي", "تفعيل live", "activate live"]),
        ("trading", ["تداول", "ابدأ", "start trading", "trade"]),
    ]
    for key, words in pairs:
        if any(w in m for w in words):
            return key
    return "trading"


def build_user_context(db: Session, user: User) -> Dict[str, Any]:
    """Safe context only — no secrets."""
    dry = bool(getattr(settings, "TRADING_DRY_RUN", True))
    recent_sig = (
        db.query(SignalReceipt)
        .filter(SignalReceipt.user_id == user.id)
        .order_by(SignalReceipt.created_at.desc())
        .limit(5)
        .all()
    )
    recent_tr = (
        db.query(Trade)
        .filter(Trade.user_id == user.id)
        .order_by(Trade.created_at.desc())
        .limit(5)
        .all()
    )
    open_tr = (
        db.query(Trade)
        .filter(Trade.user_id == user.id, Trade.status.in_(["open", "pending", "partial"]))
        .count()
    )
    next_step = "register"
    if user.has_gateway_credentials:
        next_step = "subscription" if (user.subscription_tier or "free") == "free" else "tradingview"
    elif user.is_verified:
        next_step = "mt5"
    trial = TrialService(db).get_trial_status(user.telegram_id)
    try:
        plan = SubscriptionService(db).get_user_plan(user.telegram_id)
        plan_features = SubscriptionService(db).get_plan_features(getattr(plan, "tier", user.subscription_tier))
    except Exception:
        plan_features = {}
    latest_signal = recent_sig[0] if recent_sig else None
    latest_trade = recent_tr[0] if recent_tr else None
    try:
        news = NewsProtectionService().system_status()
        news_state = {"status": news.get("status"), "reason": news.get("reason")}
    except Exception:
        news_state = {"status": "unavailable", "reason": "News state unavailable"}
    today_start = __import__('datetime').datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_signals = db.query(SignalReceipt).filter(SignalReceipt.user_id == user.id, SignalReceipt.created_at >= today_start).all()
    accepted_today = sum(1 for item in today_signals if item.final_decision in {"accepted", "executed"} or item.status in {"execution", "executed", "dry_run", "partial", "pending", "unknown"})
    result_snapshot = ResultsService(db).results(user.telegram_id, "30d")
    metrics = result_snapshot.get("metrics") or {}
    return {
        "telegram_id": user.telegram_id,
        "subscription_tier": user.subscription_tier,
        "subscription_status": trial.get("status") if trial.get("active") or trial.get("status") == "EXPIRED" else ("ACTIVE" if user.subscription_expiry and user.subscription_expiry > __import__('datetime').datetime.utcnow() else "NOT ACTIVE"),
        "trial": trial,
        "plan_features": {key: plan_features.get(key) for key in ("supports_auto_trading", "supports_api", "max_trades_per_day", "max_symbols") if key in plan_features},
        "is_verified": bool(user.is_verified),
        "is_active": bool(user.is_active),
        "has_gateway": bool(user.has_gateway_credentials),
        "dry_run": dry,
        "signals_recent": [
            {"id": s.id, "status": s.status, "source": s.source}
            for s in recent_sig
        ],
        "trades_recent": [
            {"id": t.id, "symbol": t.symbol, "status": t.status, "profit_loss": float(t.profit_loss) if t.profit_loss is not None else None}
            for t in recent_tr
        ],
        "latest_signal": {"status": latest_signal.status, "reason": latest_signal.rejection_reason, "news_status": latest_signal.news_status} if latest_signal else None,
        "latest_trade": {"symbol": latest_trade.symbol, "status": latest_trade.status, "profit_loss": float(latest_trade.profit_loss) if latest_trade and latest_trade.profit_loss is not None else None} if latest_trade else None,
        "results_30d": {key: metrics.get(key) for key in ("total_closed_trades", "win_rate", "total_pnl")},
        "signals_today": len(today_signals),
        "accepted_signals_today": accepted_today,
        "rejected_signals_today": len(today_signals) - accepted_today,
        "news": news_state,
        "risk": {"default_risk_factor": user.default_risk_factor, "configured": user.default_risk_factor is not None},
        "open_trades": open_tr,
        "next_best_step": next_step,
        "trading_mode": getattr(user, "trading_mode", None) or "demo",
    }


def answer(
    message: str,
    *,
    lang: Optional[str] = None,
    db: Optional[Session] = None,
    user: Optional[User] = None,
) -> Dict[str, Any]:
    language = detect_lang(message, lang)
    intent = _match_intent(message)
    # Hard refuse: AI must not change trading mode
    low = (message or "").lower()
    if any(x in low for x in ("فعّل live", "فعل live", "activate live", "switch to live", "set live", "غير إلى live", "تحويل إلى live")):
        language = detect_lang(message, lang)
        refuse = {
            "ar": "لا أستطيع تفعيل LIVE أو تغيير وضع التداول. استخدم زر Trading Mode في لوحة الويب مع التأكيد المطلوب.",
            "en": "I cannot enable LIVE or change trading mode. Use the Trading Mode control in the web dashboard with the required confirmation.",
        }[language]
        return {
            "reply": refuse + ({
                "ar": "\n\n(المساعد للتعليم فقط — لا ينفذ صفقات.)",
                "en": "\n\n(Guidance only — never executes trades.)",
            }[language]),
            "language": language,
            "intent": "refuse_mode_change",
            "provider": "knowledge_base",
            "context": {},
            "configured": False,
        }

    base = KB.get(intent, KB["trading"])[language]

    ctx_note = ""
    context: Dict[str, Any] = {}
    if db is not None and user is not None:
        context = build_user_context(db, user)
        if language == "ar":
            ctx_note = (
                f"\n\n— حالة حسابك —\n"
                f"الخطة: {context.get('subscription_tier')}\n"
                f"بوابة MT5: {'مربوطة' if context.get('has_gateway') else 'غير مربوطة'}\n"
                f"Dry Run: {'نعم' if context.get('dry_run') else 'لا'}\n"
                f"صفقات مفتوحة: {context.get('open_trades')}\n"
                f"حالة Trial: {context.get('trial', {}).get('status')}\n"
                f"إشارات اليوم: {context.get('signals_today')} | المقبولة: {context.get('accepted_signals_today')} | المرفوضة: {context.get('rejected_signals_today')}\n"
                f"آخر إشارة: {(context.get('latest_signal') or {}).get('status', 'غير متاح')}\n"
                f"News Protection: {(context.get('news') or {}).get('status', 'غير متاح')}\n"
                f"وضع التداول: {context.get('trading_mode')}\n"f"الخطوة التالية المقترحة: {context.get('next_best_step')}"
            )
        else:
            ctx_note = (
                f"\n\n— Your account —\n"
                f"Plan: {context.get('subscription_tier')}\n"
                f"MT5 gateway: {'connected' if context.get('has_gateway') else 'not connected'}\n"
                f"Dry Run: {'yes' if context.get('dry_run') else 'no'}\n"
                f"Open trades: {context.get('open_trades')}\n"
                f"Trial: {context.get('trial', {}).get('status')}\n"
                f"Signals today: {context.get('signals_today')} | accepted: {context.get('accepted_signals_today')} | rejected: {context.get('rejected_signals_today')}\n"
                f"Latest signal: {(context.get('latest_signal') or {}).get('status', 'unavailable')}\n"
                f"News Protection: {(context.get('news') or {}).get('status', 'unavailable')}\n"
                f"Trading mode: {context.get('trading_mode')}\n"f"Suggested next step: {context.get('next_best_step')}"
            )

    # Optional external LLM — never required; keys stay backend-only
    provider = os.getenv("AI_PROVIDER", "").strip().lower()
    api_key = os.getenv("AI_API_KEY") or os.getenv("OPENAI_API_KEY")
    provider_status = "knowledge_base"
    if api_key and provider in ("openai", "compatible"):
        provider_status = "provider_configured_unused_fallback_kb"
        # Intentionally use KB as source of truth for safety; do not send secrets to third parties by default.

    disclaimer = {
        "ar": "\n\n(المساعد للتعليم والإرشاد فقط — لا ينفذ صفقات ولا يضمن أرباحاً.)",
        "en": "\n\n(Assistant is for guidance only — it never executes trades and does not guarantee profits.)",
    }[language]

    return {
        "reply": base + ctx_note + disclaimer,
        "language": language,
        "intent": intent,
        "provider": provider_status,
        "context": {
            "subscription_tier": context.get("subscription_tier"),
            "has_gateway": context.get("has_gateway"),
            "dry_run": context.get("dry_run"),
            "next_best_step": context.get("next_best_step"),
            "open_trades": context.get("open_trades"),
        } if context else {},
        "configured": bool(api_key),
    }


def quick_actions(lang: str = "ar") -> List[str]:
    if lang == "en":
        return [
            "How do I register?",
            "How do I connect MT5?",
            "How do I activate my subscription?",
            "How do I start trading?",
            "How do I connect TradingView?",
            "Where are my signals?",
            "Why wasn't my trade executed?",
            "What is Stop Loss?",
            "What is Take Profit?",
        ]
    return [
        "كيف أسجل؟",
        "كيف أربط MT5؟",
        "كيف أفعل الاشتراك؟",
        "كيف أبدأ التداول؟",
        "كيف أربط TradingView؟",
        "أين أرى إشاراتي؟",
        "لماذا لم تنفذ الصفقة؟",
        "ما هو Stop Loss؟",
        "ما هو Take Profit؟",
    ]
