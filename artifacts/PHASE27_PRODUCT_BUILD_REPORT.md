# PHASE 27 — Product Build Report

## 1. PRODUCT FLOW BEFORE

The project already had authenticated web APIs, a Telegram registration/trading flow, a TradingView webhook path, SignalPipeline, subscription checks, risk calculation, TradeExecutor, and dry-run guards. The main product gaps were unclear account/subscription status, an incorrect gateway-presence check, Telegram command discoverability, and UI affordances that implied LIVE mode or manual execution.

## 2. PRODUCT FLOW AFTER

The existing flow remains intact:

`register → gateway status → subscription status → TradingView → SignalPipeline → subscription/feature checks → risk/position sizing → TradeExecutor → DRY RUN result → dashboard/Telegram`

No parallel execution path or new signal strategy was added.

## 3. USER ONBOARDING

- Telegram `/start` now reports the actual gateway credential/connection state instead of unconditionally saying MT5 is connected.
- Telegram exposes `/account`, `/status`, `/trades`, and `/subscription` using existing handlers/services.
- Web dashboard presents account, subscription, and safety status together.
- Authentication and registration gates remain enforced.

## 4. MT5 CONNECTION

- `User.has_gateway_credentials` is now a real boolean property based on both gateway fields.
- Dashboard and MT5 status continue to use the existing runtime gateway connection and show no fabricated balance data.
- No passwords, keys, or tokens are returned.

## 5. SUBSCRIPTION/TRIAL

- Dashboard now exposes the existing plan, status, expiry, daily usage, remaining allowance, and feature snapshot.
- Existing `SubscriptionService` remains the source of plan limits.
- No limits or feature checks were relaxed.

## 6. TRADINGVIEW

The TradingView webhook path was not redesigned. Existing authentication, schema/timestamp validation, replay and duplicate protection, rate limiting, symbol validation, subscription checks, and SignalPipeline routing remain in place. The web signal detail screen is now explicitly read-only and no longer advertises a nonexistent manual-execution endpoint.

## 7. SIGNAL PIPELINE

No second pipeline was introduced. Existing normalization, validation, receipt claiming, confirmation, and executor routing remain the execution path.

## 8. RISK

No risk calculation, symbol policy, position sizing, emergency stop, or risk-engine check was changed.

## 9. EXECUTION

No direct web execution was added. The existing TradeExecutor remains responsible for subscription, risk, duplicate, gateway, and dry-run enforcement.

## 10. TRADE STATUS

- Trade detail now displays a small timeline derived only from persisted trade fields: signal recorded, position calculated when a size exists, and the persisted execution result/status.
- UNKNOWN or other non-success states are not converted into success.

## 11. DASHBOARD

- Added clear account connection, subscription, allowance, and DRY RUN cards.
- Removed the LIVE mode control from the dashboard while the environment is dry-run.
- Existing recent signals, trades, risk, settings, support, and admin pages remain in place.

## 12. TELEGRAM

- Added discoverable aliases/status commands without replacing existing handlers.
- `/status` gives connection, plan, expiry, and dry-run state without credentials.
- Existing registration and authorization middleware remains active for account/trading commands.

## 13. DRY-RUN SAFETY

`TRADING_DRY_RUN` remained true. The web dashboard and Telegram status now use an explicit DRY RUN indicator and do not present LIVE as the current operating state. No real broker order was sent.

## 14. TEST RESULTS

- `python -m compileall -q .`: passed.
- `python -m pytest --collect-only -q`: 105 tests collected.
- `python -m pytest -q`: 105 passed, with the existing Starlette/httpx deprecation warning.
- Settings verification with non-production test environment values: `TRADING_DRY_RUN=True`.
- No `.env` file exists.
- `git diff --check`: passed.

## 15. FILES MODIFIED

PHASE 27 changed:

- `database/models.py`
- `bot/handlers.py`
- `bot/main.py`
- `web/api/dashboard.py`
- `web/api/trades.py`
- `web/static/js/app.js`

Pre-existing PHASE 26 modifications remain in the worktree and were not reverted.

## 16. FILES CREATED

- `artifacts/PHASE27_PRODUCT_BUILD_REPORT.md`

No new runtime architecture, migration, dependency, or secret file was created.

## 17. FILES DELETED

0. No existing project file was deleted.

## 18. REMAINING FUNCTIONAL GAPS

- The web login still depends on the existing API-key/JWT login flow; a user-facing one-time Telegram login flow is not implemented.
- Real gateway synchronization remains dependent on the configured runtime provider and is not verifiable against production here.
- Historical broker-level execution events are not stored as a dedicated event stream; the displayed timeline is limited to persisted trade state.
- The existing Starlette/httpx compatibility warning remains; no dependency was installed or upgraded in this phase.

## 19. NEXT PHASE

Deployment/integration verification only after an operator supplies safe non-production gateway/database configuration. Do not enable live trading or begin PHASE 28 until that verification is approved.
