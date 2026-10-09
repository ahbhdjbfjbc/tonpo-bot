# PHASE 26.3 — Security & Production Hardening

## Scope and safety

- Baseline: `eb90c8e` — PHASE 25 verified.
- Work was limited to this project directory.
- No production database, broker, MT5 account, live endpoint, Git remote, push, or real order was used.
- `TRADING_DRY_RUN` remains `true` in project configuration.
- No real secrets, passwords, API keys, tokens, or private keys are included in this report.

## Repairs completed

| Area | Result |
|---|---|
| Trade error responses | `services/trade_executor.py` no longer returns raw exception text from calculation, close, or modify failures. Internal logs retain only operation context and exception type. |
| Telegram admin errors | `bot/middleware.py` no longer sends raw exception text to admins; it sends the exception type and a protected-log reference. |
| Webhook exception logging | `web/api/webhooks.py` replaced two raw `logger.exception` calls with exception-type-only logging. Request bodies, headers, provider details, and tracebacks are not emitted by these paths. |
| Admin bootstrap | `web/api/auth.py` no longer accepts `JWT_SECRET` as an admin API credential. Optional bootstrap now requires a separately configured `ADMIN_API_KEY`; absent configuration fails closed. |
| Persistence filtering | `database/db_persistence.py` now filters an explicit set of credential field names instead of substring-matching arbitrary key names. Trading state is not filtered merely because a key contains words such as `token` or `secret`. |
| CORS | `web/cors.py` now accepts only explicit HTTP(S) origins without wildcard, paths, query strings, fragments, or embedded credentials. Local-only fallback remains available. |
| Regression tests | Added admin-bootstrap and invalid-CORS-origin coverage without real credential values. |

## Intentionally unchanged

- No migrations were modified, created, deleted, or downgraded.
- Migration 015 was not downgraded.
- `web/runtime.py` was not changed; it contains no CORS policy.
- `requirements.txt`, `pyproject.toml`, and the existing `requirements-dev.txt` declaration were not changed in this phase. No dependency was installed.
- TradingView authentication, replay protection, duplicate protection, rate limiting, schema validation, symbol validation, timestamp validation, risk engine routing, subscription checks, and feature access checks were not weakened.
- No new signal source or autonomous bot signal strategy was added.

## Credential security status

**BLOCKED for full at-rest remediation.** Existing plaintext-capable fields remain in the legacy/current schema, including gateway and user API credential fields. The existing Fernet helper remains available, but applying it safely to persisted values requires a key-ownership/rotation policy, historical-data migration, re-encryption procedure, and deployment secret provisioning. Those decisions were not invented in this phase.

Safe exposure reductions completed:

- Raw credential-bearing exception results were removed from the reviewed execution paths.
- Public user serializers continue to omit stored credentials.
- JWT signing secret is no longer accepted as an admin API key.
- No credential values were logged or added to source, tests, or reports.

## Admin authentication status

The previous JWT-secret bootstrap path was removed. Normal user API-key authentication and JWT issuance remain unchanged. Optional admin bootstrap is fail-closed unless a distinct deployment-provided `ADMIN_API_KEY` exists and the Telegram ID is in the configured admin list.

## Exception leakage status

The PHASE 26.3 target paths now return/log safe generic messages or exception types only. Existing unrelated legacy raw-exception paths remain outside this minimal patch scope, including dormant backup code and some older payment/admin notification paths; they require separate review if they are reachable in deployment.

## CORS status

Credentialed CORS uses configured explicit origins. If configuration is absent, the fallback is limited to localhost development ports. No production domain is assumed. TradingView webhook authentication is server-to-server and is not controlled by browser CORS.

## Persistence filtering status

Filtering is recursive for `user_data` only and targets explicit credential field names. It does not filter chat data, bot data, callback data, trade records, subscription records, or audit records. Historical serialized values are not scrubbed automatically.

## HTTPX/Starlette status

The existing `httpx2>=2.0.0` declaration was not changed or installed. The package name is valid and is the transport recommended by current Starlette documentation; the active environment still reports the deprecation warning because `httpx2` is not installed. Compatibility should be confirmed in the project’s isolated dependency environment before any future pin/range decision. No major upgrade was performed.

## TradingView and trading safety status

No security control was weakened. The webhook still requires authentication, rate limiting, timestamp/replay checks, schema validation, and pipeline routing. The pipeline continues to enforce symbol/risk validation, subscription limits, feature access, and dry-run behavior. `TRADING_DRY_RUN` remains `true`; no real order was sent.

## Verification

- `python -m compileall -q .`: passed.
- `python -m pytest --collect-only -q`: 105 tests collected.
- `python -m pytest -q`: exit code 0; 105 tests passed; the known Starlette/httpx deprecation warning remains.
- `.env`: absent.
- Credential-signature scan of source outside tests/reports: no matches.
- Deleted baseline paths: 0.
- `git diff --check`: passed.
- No production database connection was made.

## Remaining blockers

1. Full credential encryption and historical re-encryption require an architecture/key-rotation decision.
2. PostgreSQL migration/runtime compatibility still needs verification against a disposable PostgreSQL database; production remains prohibited.
3. Existing legacy raw-exception paths outside the PHASE 26.3 target paths need a separate reachability review.
4. The active environment still lacks `httpx2`; dependency installation was intentionally not performed.

## PHASE 26.4 plan

- Decide credential ownership, encryption boundary, KMS/secret-manager custody, key versioning, rotation, recovery, and revocation behavior.
- Design a reviewed, non-destructive migration and historical re-encryption process with rollback/recovery safeguards.
- Inventory legacy credential-capable columns and persisted bot state without exporting or printing values.
- Verify migrations 001–016 on disposable PostgreSQL, including supported upgrade paths and migration 003 assumptions; do not downgrade 015.
- Review remaining reachable raw-exception paths and define a consistent safe error taxonomy.
- Resolve the isolated Starlette/httpx2 dependency policy after compatibility testing.

## Integrity

- Files deleted: 0.
- Tests deleted or disabled: 0.
- No commit, push, remote operation, dependency installation, production database access, or real trading occurred.
