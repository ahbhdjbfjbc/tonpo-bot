# FINAL UI + TRADE + AI VERIFICATION

`TRADING_DRY_RUN=true` (unchanged)

## A. UI mapping

| Page | Endpoint | Works |
|------|----------|-------|
| Login | POST /api/auth/login | Yes |
| Dashboard | GET /api/dashboard | Yes |
| Signals | GET /api/signals | Yes + detail /api/signals/{id} |
| Trades | GET /api/trades | Yes + detail /api/trades/{id} |
| MT5 | GET /api/mt5/status | Yes (honest not connected) |
| Risk | GET /api/risk | Yes |
| Settings | GET/PATCH /api/settings | Yes + Save UI |
| Support | GET/POST /api/support/tickets | Yes |
| Admin | GET /api/admin/* | Read-only |
| AI | POST /api/assistant/chat | Yes (KB) |
| Manual execute | POST /api/signals/{id}/manual-execute | Dry-run only |
| WS | /ws | Auth + isolation |

## B–G. Trading / AI / SL-TP / WS
- TradingView → webhook → pipeline → dry_run verified by tests
- Manual execute returns dry_run under TRADING_DRY_RUN
- Close/Modify: not in Web UI (documented; use Telegram)
- AI: no trade execution path
- SL required on webhook; TP carried
- WS JWT + isolation tests pass

## H. Button audit

| Button | Endpoint | Works | Risk |
|--------|----------|-------|------|
| Login | /api/auth/login | Yes | N/A |
| Save settings | PATCH /api/settings | Yes | N/A |
| Support send | POST /api/support/tickets | Yes | N/A |
| Manual execute | .../manual-execute | Dry-run block | Yes |
| Close/Modify | — | Absent | — |
| AI send | /api/assistant/chat | Yes | No trade |

## I. Tests
**84 passed, 0 failed, 15 warnings**

## J. Safety
- No secrets printed/replaced
- No real trades
- TRADING_DRY_RUN=true
- No destructive DB ops
- No files deleted intentionally

## K. Limitations
- Close/Modify not in Web
- AI is knowledge-base (external LLM optional, unused by default)
- Authenticated screenshots need real user credentials (not provisioned)
- Docker may be unavailable in some environments

## Verdict
**READY WITH WARNINGS** (not real-trading activation; dry-run retained by design)
