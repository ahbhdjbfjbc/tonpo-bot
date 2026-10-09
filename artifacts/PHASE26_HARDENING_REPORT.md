# PHASE 26.1 — Production Hardening Report

## Project

- Path: `/data/data/com.termux/files/home/tonpo-phase25-verified/tonpo-bot-main`
- Initial tree was unpacked without Git metadata. A local-only repository was initialized; no remote was configured.
- Baseline commit: `eb90c8e` — `PHASE 25 verified baseline`.
- No production database, broker account, production credential, wallet key, or live trading endpoint was used.

## Baseline

- The baseline inventory contained 154 project files/paths.
- `.env` was absent; `.env.example` was present.
- Baseline environment/config kept `TRADING_DRY_RUN=true`.
- At baseline, CORS allowed `*` while enabling credentials. Encryption/JWT code could generate fallback keys, and registration placed the pending MT5 password in persistent Telegram user data.

## Audit

Reviewed application/configuration, database and all 16 migration scripts, gateway, services, web APIs, tests, artifacts, deployment/dependency files, and credential/trading paths. Checked Python syntax/importability, settings validation, CORS policy, public user response shape, password persistence/logging, migration graph and offline SQL generation, and dry-run guards.

## Repairs

| File | Change and reason |
|---|---|
| `.env.example` | Removed misleading key examples; documented blank key configuration, local CORS origins, and retained dry-run true. |
| `config/settings.py` | Added strict Fernet and JWT-secret validation and explicit configurable local CORS-origin validation. |
| `web/cors.py` | Added origin resolution that rejects wildcard origins. |
| `web/app.py` | Configured credentialed CORS from validated explicit origins; sanitized error logging. |
| `tests/test_cors_policy.py` | Added default, wildcard rejection, and preflight policy coverage. |
| `services/auth.py` | Removed generated encryption/JWT fallback secrets; key use now fails closed and error logs avoid exception contents. |
| `bot/registration.py` | Kept pending MT5 passwords in process memory only, consumed/cleared them on relevant flows, and removed password-bearing confirmation display. |
| `database/db_persistence.py` | Filters credential-like keys from user data before persistence/load exposure. |
| `tests/test_credentials_security.py` | Added key-validation, redaction, API response, registration persistence, and persistence-filter coverage. |
| `gateway_client/adapter.py` | Removed exception/credential contents from gateway-facing error logs and responses. |
| `bot/settings.py`, `bot/main.py`, `bot/callbacks.py`, `bot/message_utils.py`, `bot/trading.py`, `database/utils.py`, `services/cache.py`, `services/monitoring.py`, `services/notification.py`, `services/payment.py`, `services/queue.py`, `services/subscription.py`, `web/api/dashboard.py`, `web/api/mt5.py`, `web/api/webhooks.py`, `web/runtime.py` | Redacted exception details from runtime logs in credential-capable or external-operation paths. |
| `bot/admin.py`, `core/models.py`, `database/repositories.py` | Replaced deprecated `datetime.utcnow()` use while preserving naive UTC values where required; repository error logging was also redacted. |
| `database/database.py` | Corrected the SQLAlchemy declarative base import used by database initialization. |
| `database/models.py` | Corrected the legacy MT5-password model comment; no schema change was made. |

No existing file was removed. No test was removed or skipped. No migration was altered or removed.

## CORS

- Before: wildcard origin (`*`) with `allow_credentials=True`.
- After: explicit HTTP(S) origins, defaulting to localhost/127.0.0.1 on ports 3000 and 5173. Origins are configurable through `CORS_ORIGINS`; wildcard, malformed origins, paths, and embedded credentials are rejected. Credentialed requests remain enabled only for listed origins.
- CORS and authentication-focused tests passed as part of the full suite.

## Credential security

- Encryption key: must now be explicitly supplied and parse as a Fernet key. Missing/invalid keys fail when encryption is used; no random fallback is generated.
- JWT secret: must be configured and at least 32 characters; no random fallback is generated.
- MT5 registration password: no longer stored in Telegram persistent user data and is not printed in the confirmation prompt. Persistent user data is filtered for credential-like fields.
- Public user response tests confirm MT5 password and gateway API key are not returned.
- The repository still has plaintext-sensitive credential fields including `users.gateway_api_key`; historical secrets already stored in production databases/persistence were not inspected or modified. No production database was accessed. These need a separately reviewed encryption/migration and data-remediation plan before production use.
- A credential-like scan found only test/example or application-input patterns; no private-key header or literal production secret was identified. `.env` does not exist. Values were not printed.

## Database and migrations

- Revisions 001–016 are ordered as a linear chain; each defines upgrade and downgrade functions.
- SQLite in-memory model metadata creation succeeded (18 tables).
- Offline PostgreSQL-dialect SQL generation succeeded for the full upgrade path and the `016 → 015` downgrade; no database connection was made.
- SQLite execution cannot validate PostgreSQL-specific migration 003. No live PostgreSQL schema was checked.
- Migration 015 intentionally refuses downgrade to protect admin audit/support data. This irreversible downgrade behavior was not changed.
- Compatibility of the final production schema with deployed data remains unverified.

## Warnings

- **Compatibility/deprecation:** one test-run warning: Starlette reports that using `httpx` with `starlette.testclient` is deprecated and recommends `httpx2`. No dependency was upgraded.
- **Actual risk:** sensitive gateway/API credential model fields and any historic persisted credential values require a reviewed at-rest encryption and data-remediation migration.
- **Verification limit:** PostgreSQL-specific runtime migration behavior and deployed schema/data compatibility were not exercised; validation used offline SQL generation only.
- **Operational prerequisite:** deployment must provide strong `ENCRYPTION_KEY` and `JWT_SECRET` values through its secret manager. The repository example intentionally contains no real values.

## Tests

- `python -m compileall -q .`: passed.
- `python -m pytest --collect-only -q`: 102 tests collected.
- `python -m pytest -q`: passed, 102 passed, 0 failed, 0 skipped, 0 errors.
- Warnings: 1 (Starlette/httpx compatibility deprecation above).
- No real order execution occurred; trading-path tests use dry-run and mocks.

## Trading safety

- `TRADING_DRY_RUN=true` in `.env.example`; Settings defaults to true.
- Dry-run executor and trading-mode tests passed. Web runtime reports dry-run by default and test fixtures use mocked gateways.
- No order was sent, no broker account was connected, and no live trading was enabled. Real trades: **0**.
- The process environment did not define `TRADING_DRY_RUN`; the checked project configuration/example remain true.

## Integrity

- Baseline paths: 154; missing baseline paths: 0.
- Current inventory: 159 project files excluding Git/cache data; all 154 baseline paths remain. Five paths are outside the baseline inventory: the previously generated preparation report, two new test files, `web/cors.py`, and this report.
- Files deleted: **0**. Tests deleted: **0**. Migrations deleted: **0**. Screenshots deleted: **0**. Reports deleted: **0**.
- `.env` created: **no**.
- No Git remote, push, or post-baseline commit was created.
- `git diff --check`: passed before report creation; final status/diff are included in the closing verification.

## Remaining issues

1. Plaintext credential-capable database columns and historical persisted values remain an actual production risk; safe remediation requires a planned key lifecycle and compatible migration/data cleanup.
2. PostgreSQL migration execution and the deployed database schema/data were not tested because production connectivity is prohibited and revision 003 is PostgreSQL-specific.
3. Migration 015 does not support downgrade by design.
4. Starlette/httpx test-client deprecation remains pending a deliberate dependency compatibility update.

## Final verdict

**READY WITH WARNINGS** — the requested hardening checks and tests pass, but this is not a production-ready certification. The unresolved at-rest credential risk and unverified deployed PostgreSQL schema must be addressed before production use.
