# PHASE 31 — TradingView Final Integration

STATUS: COMPLETE

TradingView webhook:
- Authenticated `POST /api/webhooks/tradingview` is the single web ingress.
- Payloads cannot select `user_id`, `account_id`, or `subscription_id`; target identity comes from `TRADINGVIEW_TELEGRAM_ID` configuration.
- No direct webhook-to-broker path exists; processing uses the existing `SignalPipeline`, whose only execution boundary is `TradeExecutor`.

Authentication:
- Secret is read from configuration/environment and compared with constant-time comparison.
- Missing/wrong authentication is rejected. Secrets are not logged, returned, or shipped to frontend.

Validation:
- Required action, symbol, SL, TP, timestamp, and signal id are enforced.
- Invalid action, malformed JSON, non-finite numbers, invalid prices, invalid timestamps, expired timestamps, unsupported symbols, and identity fields are rejected fail-closed.

Symbol normalization:
- Canonical symbols are checked against configured allowed symbols.
- Alternate symbols work only through explicit `TRADINGVIEW_SYMBOL_MAP`; unknown/ambiguous symbols are rejected.

Replay protection:
- Timestamp freshness is validated.
- Durable receipt idempotency is used by the existing persistence layer; process-local seen-ID state is not the source of truth.

Duplicate protection:
- `SignalReceipt` unique `(user_id, idempotency_key)` claim prevents concurrent duplicate processing.
- Repeated ids do not create a second order. Unknown execution returns reconciliation-required and is never blindly retried.

User isolation:
- Webhook identity is configuration-bound and cannot be overridden by payload fields.
- Authenticated API queries remain scoped to the current user. Cross-user payload selection is rejected.

Subscription:
- Existing backend subscription, trial, feature, and daily limit checks remain in `SignalPipeline`; frontend cannot bypass them.

Risk:
- Existing parser validation, risk controls, symbol/account policies, position sizing, and execution safeguards remain in the shared pipeline. No fixed-lot fallback was added.

News Protection:
- TradingView signals use the existing `NewsProtectionService` and Trading Economics integration. Active, stale, and unavailable states remain blocking/fail-closed. Tests use mocks only.

Signal lifecycle:
- Signal Center uses persisted receipt status and decision context. It does not claim validation/approval stages that are not persisted, and never shows APPROVED for a rejected receipt.

UI:
- Signal Center and Results Center show status, timestamp, symbol/direction where available, news state, execution/trade state, and rejection reason.
- Empty, loading, error, responsive/mobile, unauthorized, and expired-subscription states use safe user-facing messages.
- Navigation references, API references, core buttons, and no-direct-execute UI wiring were verified.

Telegram:
- Existing Telegram commands and notification flow remain on current services/pipeline. Signal decisions, rejection reasons, News Protection, and execution state are shown without secrets.

Tests:
- Before Phase 31: 96 tests.
- After Phase 31: 102 tests.
- Full suite: `PYTHONPATH=. pytest -q` — PASS.
- Added coverage for identity isolation, finite price validation, explicit symbol mapping, timestamp validation, safe unknown execution errors, webhook auth/validation/replay/duplicate behavior, dry-run, and UI/API integration.
- No real MT5, Trading Economics API, Production DB, credentials, or live execution used.

Compile:
- `python -m compileall -q bot config core database gateway_client services web tests`: PASS

JavaScript:
- `node --check web/static/js/app.js`: PASS

TRADING_DRY_RUN:
- `true`
- `.env.example` and `config/settings.py` remain true/default true. No live trading or real-money execution was performed.

Deleted files:
0

Modified migrations:
0

Remaining blockers:
- Runtime deployment must provide the configured `TRADINGVIEW_WEBHOOK_SECRET` and `TRADINGVIEW_TELEGRAM_ID`; this is external configuration, not a code defect.
- Live broker/Trading Economics validation was intentionally not performed because of the mandatory safety rules; mocked/in-memory coverage is complete.
