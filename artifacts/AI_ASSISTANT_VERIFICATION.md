# AI Assistant Verification

## Architecture
- Service: `services/ai_assistant.py` (knowledge base, bilingual)
- API: `web/api/assistant.py` — `/api/assistant/status`, `/quick-actions`, `/chat`
- Frontend: floating panel in `index.html` + `app.js` (`initAi`)
- Optional `AI_API_KEY` / `OPENAI_API_KEY` env only (backend); site works without them via KB

## Behavior
- Teacher + guide only
- Never calls TradeExecutor, Gateway, or place_market
- User context: subscription, gateway flag, dry_run, recent signal/trade counts, next_best_step
- Isolation: chat requires JWT; context built from `user.id` only
- No secrets in responses
- Disclaimer: does not execute trades / no profit guarantee

## Languages
- Arabic (RTL) / English (LTR)
- Language selector + auto-detect Arabic script
- Quick actions in both languages

## Tests
- `tests/test_ai_assistant.py` — KB AR/EN, auth required, no executor in module
