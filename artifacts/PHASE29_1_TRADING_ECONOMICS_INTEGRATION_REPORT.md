# PHASE 29.1 — Trading Economics Integration

## Final verdict

The existing News Protection path now uses a Trading Economics adapter by
default. The adapter normalizes the documented calendar response, caches a
bounded snapshot, and fails closed when configuration, transport, freshness,
or payload validation is unsafe. No live provider credential was available or
used during verification, so external connectivity remains unverified.

## Trading Economics integration

- Endpoint: the documented date-bounded calendar endpoint.
- Fields normalized: `CalendarId`, `Date`, `Event`/`Category`, `Currency`, and
  `Importance`.
- Importance mapping: 1 low, 2 medium, 3 high.
- Timestamps are normalized to UTC.
- Provider failures never become an empty calendar or an allow decision.

## Provider adapter and configuration

Implemented `services/trading_economics.py` and extended
`services/news_protection.py`.

Configuration is in `config/settings.py` and `.env.example`:

- `TRADING_ECONOMICS_API_KEY`
- `TRADING_ECONOMICS_BASE_URL`
- `TRADING_ECONOMICS_TIMEOUT_SECONDS`
- `TRADING_ECONOMICS_CACHE_SECONDS`
- `TRADING_ECONOMICS_STALE_AFTER_SECONDS`

The API key is optional only at configuration-load time; when absent, new
trades are blocked. It is not logged, serialized, returned by an API, sent to
Telegram, or placed in frontend state. Its settings representation is also
excluded from `repr`.

## Cache and freshness

Fresh snapshots are reused. Expired snapshots trigger a refresh. A refresh
failure may use a bounded still-safe cached snapshot; once the configured
stale age is exceeded, the provider raises a stale-data condition and the
signal is blocked. Empty, malformed, invalid-timestamp, and invalid-importance
responses fail closed.

## Symbol/currency mapping

The existing symbol normalizer is reused. Base pairs and broker suffixes such
as `EURUSDm` and `USDJPY.a` resolve to their two three-letter currencies.
Only high-impact events relevant to either currency are blocking.

## News decision logic and automatic resume

The existing order remains authoritative:

`TradingView → validation/replay/duplicate/rate limit → SignalPipeline → NewsProtection → subscription → risk → sizing → TradeExecutor → dry-run`.

The adapter produces `active`, `inactive`, `unavailable`, or `stale` states.
`active`, `unavailable`, and `stale` block new trades. When a valid fresh
snapshot is available and the protection window has expired, normal evaluation
automatically resumes; no restart or background job is required.

## Dashboard, Telegram, and Signal Center

The authenticated news API now exposes provider name, last update, next event,
protection end, and safe block status. Dashboard and Telegram `/news` display
safe unavailable/stale states and never expose provider responses or secrets.
Signal receipts preserve `news_status` and the existing rejection reason.

## Security and user isolation

No authentication, subscription, feature, risk, replay, duplicate, rate-limit,
ownership, or TradeExecutor boundary was weakened. No real broker or
production database was used. Existing migration 017 was inspected and left
unchanged; no duplicate migration was created.

## Tests and compile result

- `python -m compileall -q .` — passed.
- `python -m pytest --collect-only -q` — 120 tests collected.
- `python -m pytest -q` — 120 passed.
- Targeted mocked Trading Economics tests cover valid normalization, all
  documented importance levels, currency/suffix mapping, timeout/HTTP error
  fail-closed behavior, malformed/empty data, missing key, cache staleness,
  protection windows, and automatic resume.
- `TRADING_DRY_RUN=True` verified with non-production placeholder environment
  values; no database was opened by that check.
- `.env` absent; no private key or real provider credential added.

## Files modified

- `.env.example`
- `config/settings.py`
- `services/news_protection.py`
- `services/signal_pipeline.py`
- `services/results.py`
- `bot/handlers.py`
- `web/api/results.py`
- `web/static/js/app.js`
## Files created

- `services/trading_economics.py`
- `tests/test_trading_economics_provider.py` (created for this integration)
- `artifacts/PHASE29_1_TRADING_ECONOMICS_INTEGRATION_REPORT.md`

Other pre-existing PHASE 26–29 worktree additions were not removed or
rewritten.

## Files deleted

0.

## Migration status

Migration 017 was inspected and unchanged. No migration 018 was created.

## External blockers

Production deployment still requires a Trading Economics account/API key to be
provided through the deployment secret manager and a non-production smoke test
against the provider. No claim of real provider connectivity is made here.

## Remaining issues

The test environment intentionally does not call Trading Economics. Provider
plan limits, deployment secret provisioning, and production network access
remain deployment responsibilities; all repository-level integration and
mocked safety behavior are implemented.
