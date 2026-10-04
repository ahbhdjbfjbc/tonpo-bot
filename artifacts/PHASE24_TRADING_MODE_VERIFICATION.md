# PHASE 24 — Per-User DEMO / LIVE Trading Mode

## Summary
Independent `trading_mode` per user (`demo` | `live`), default **demo**.  
Environment barrier **`TRADING_DRY_RUN=true`** remains the real-order kill switch and was **not** changed.

## Files added
| Path | Purpose |
|------|---------|
| `database/migrations/versions/016_user_trading_mode.py` | Non-destructive: column + `user_audit_logs` |
| `web/api/trading_mode.py` | `GET/PATCH /api/trading-mode` |
| `tests/test_trading_mode.py` | Auth, confirm_live, isolation barriers, AI refuse, dry_run |

## Files modified
| Path | Change |
|------|--------|
| `database/models.py` | `User.trading_mode`, `User.is_live_trading`, `UserAuditLog` |
| `web/app.py` | Router include |
| `web/api/dashboard.py` | Expose `trading_mode` + badge |
| `web/static/js/app.js` | Badge, DEMO/LIVE buttons, LIVE confirmation modal |
| `bot/handlers.py` | `/start` shows 🔵 DEMO / 🟢 LIVE |
| `services/ai_assistant.py` | Explain DEMO/LIVE; **refuse** mode change |
| `services/signal_pipeline.py` | Dry-run response includes `user_trading_mode` (no bypass) |

## Migration
- **016** revises **015**
- `users.trading_mode` `String(10)` NOT NULL `server_default='demo'`
- Existing rows → **demo**
- Table `user_audit_logs` for mode changes (no secrets)

## API
- `GET /api/trading-mode` — JWT, current user only
- `PATCH /api/trading-mode` body: `{ "mode": "demo"|"live", "confirm_live": true? }`
  - LIVE without `confirm_live=true` → **400** + audit `rejected`
  - Response includes `dry_run_env` and `real_orders_possible` (false while dry-run)

## Safety matrix
| User mode | TRADING_DRY_RUN | Real MT5 orders |
|-----------|-----------------|-----------------|
| demo | true | No |
| live | true | No |
| demo | false | No (mode preference only; still needs full live path later) |
| live | false | Only when dry-run is lifted in a future phase |

## Tests
**91 passed, 0 failed, 15 warnings**

Includes: trading mode, AI refuse, webhook, websocket, e2e, dry-run suite.

## TRADING_DRY_RUN
- `config/settings.py` default **True**
- `.env.example` **true**
- Unchanged for this phase

## Remaining warnings
- Close/Modify still Telegram-only
- LIVE is a **user preference**; env dry-run still blocks broker orders
- Apply migration **016** on deploy before relying on the column in production DB

## Verdict
**READY WITH WARNINGS**

Not "READY FOR REAL TRADING".
