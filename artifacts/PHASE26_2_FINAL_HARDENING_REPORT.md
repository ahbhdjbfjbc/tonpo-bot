# PHASE 26.2 — Final Hardening Review

## PHASE 26.2 verdict

**NEEDS POSTGRES VERIFICATION — production remains blocked.** The tests pass and no new production secret exposure was found, but credential-bearing database columns remain plaintext and PostgreSQL runtime/schema compatibility has not been exercised against a disposable PostgreSQL database.

## Tests and compile

- `python -m compileall -q .`: passed.
- `python -m pytest --collect-only -q`: 103 tests collected.
- `python -m pytest -q`: exit code 0; 103 passed, 0 failed, 0 skipped, 0 errors.
- One warning remains in this active environment: Starlette's TestClient fell back to `httpx` because `httpx2` is not installed.

## Trading safety

- `TRADING_DRY_RUN` default in `config/settings.py`: `true`.
- `.env.example`: `TRADING_DRY_RUN=true`.
- No process environment override was set. No trading command, broker connection, real order, or production database connection was used.

## A) Credential-storage findings

No credential values are included in this report.

| Credential/data | Location and handling | Storage assessment / paths |
|---|---|---|
| Gateway API key | `users.gateway_api_key`, added by migration 004; written by Telegram registration and settings update handlers; loaded by `UserRepository.get_gateway_users()` and passed to the gateway client. | Stored as plaintext SQL `Text`. Create/read/update/clear paths exist. The API's public user serializers omit it. |
| User API key | `user_settings.api_key`; generated as a random token by `SettingsRepository.generate_api_key()`, then sent once to the user in Telegram. Authentication compares the submitted token directly with the DB value; revoke clears it. | Stored as plaintext, not hashed. Rotation overwrites the previous key. This needs an architecture and migration decision before changing storage. |
| Legacy MT5 password | `users.mt5_password` remains as a nullable model column. Migration 012 clears existing values and makes it nullable; current registration forwards the password to the gateway and does not write it to this column. | Any values in deployed databases or old persistence rows require a data review; this review did not connect to or inspect a deployed database. The column is plaintext-capable. |
| Legacy MT5 account/server and MetaAPI token | `users.mt5_account_id`, `users.mt5_server`, and `users.metaapi_token` remain in the model. No active application write path for `metaapi_token` was found in the reviewed source. | Account/server are identifiers; MetaAPI token is a plaintext-capable legacy field. Do not assume deployed rows are empty without PostgreSQL verification. |
| Telegram persistence | `bot_persistence_store.value` stores serialized state as plaintext JSON. Current user-data handling filters keys that look credential-related on load and update. | This is key-name filtering, not encryption. It does not guarantee cleanup of old serialized values already on disk, nor does it cover arbitrary values stored under innocuous keys. Historical rows need reviewed cleanup. |
| JWT/session token | JWT signing key is read from validated settings/environment; API login returns a JWT containing user identity and timestamps. | Signing secret is not generated or stored by the application. JWT is returned as the intended session credential; the public user object omits DB gateway/API credentials. |
| Telegram, webhook, billing and AI credentials | Configuration is read from environment/settings; payment/gateway client objects may hold keys in process memory while operating. | No real values were printed or found by private-key/JWT/access-key signature checks. `.env` is absent. |
| Password hashing helper | `EncryptionService.hash_password()` uses PBKDF2-HMAC-SHA256 with a random salt. | This helper returns a derived hash and salt; it does not provide encryption for the gateway/API credential columns described above. |

### Logs and API objects

- Raw exception text/tracebacks were found in `BaseRepository._safe_query()`, the Telegram dispatcher error handler, monitoring, and trade-executor failure logs. These active paths now log exception classes (retaining safe operation/user identifiers where useful) and re-raise or continue their prior handling.
- Added a regression test proving the database exception message is not copied into logs.
- The unreferenced `bot/main_backup.py` backup still contains older raw exception logging. Static import inspection found no current entry point importing it; it was left unchanged as a dormant backup, and must not be used as a production entry point without separate review.
- The reviewed `/api/auth` public user object returns selected profile fields and a gateway-presence boolean, not credential fields. The login response intentionally includes the newly issued JWT.
- The bot intentionally displays a newly generated user API key once in Telegram; users must protect that chat and revoke the key if exposed.

### Encryption key

- `ENCRYPTION_KEY` is required and validated as a Fernet key. The application loads it from settings/environment; it does not generate a random replacement or persist a fallback key.
- It survives process restart only if deployment supplies the same stable value. Losing or changing the key makes ciphertext encrypted under the old key undecryptable; there is no key versioning/rotation flow in the current design.
- The current registration flow stores the gateway API key directly in the database and does not call `encrypt_mt5_password()`. Thus the Fernet helper does not protect the active gateway-key persistence path.
- No schema or encryption architecture change was made. Key custody, versioning/rotation, field encryption, and historical data remediation require a Phase 27 design and migration plan.

## B) PostgreSQL compatibility

- Migrations 001–016 form the recorded linear chain; all 16 revisions remain present.
- Migration 003 contains PostgreSQL-specific catalog/PL/pgSQL logic (`pg_constraint` and a `DO $$` block) for dropping a constraint safely before altering `telegram_id` to `BIGINT`. SQLite cannot execute that block; this explains the SQLite migration-test limitation.
- The PostgreSQL-specific block is consistent with the project's PostgreSQL target. Static review did not identify evidence that the failure is a PostgreSQL incompatibility; it is an SQLite portability limitation.
- Other model types reviewed (`JSON`, `Text`, integer/boolean/date columns and ordinary indexes) are supported by PostgreSQL. Offline PostgreSQL SQL generation had passed in the Phase 26.1 review. No production database was contacted, and no local PostgreSQL service was started for this review.
- Migration 015's downgrade is intentionally unavailable; it was not invoked or changed.
- **PostgreSQL verdict: NEEDS POSTGRES VERIFICATION.** Run the complete chain on a disposable PostgreSQL database, including a clean install and the supported upgrade path from the expected existing schema. Compare the resulting schema to current models and verify migration 003's constraint/index assumptions and migration 012's data handling. Do not use production for this verification.

## C) Starlette/httpx warning

- Installed versions: FastAPI `0.142.2`, Starlette `1.7.0`, `httpx` `0.28.1`; `httpx2` is not installed in this environment.
- `fastapi.testclient.TestClient` delegates to Starlette. The installed Starlette TestClient first tries `httpx2`; when it is missing, it falls back to `httpx` and emits the observed deprecation warning.
- `requirements-dev.txt` previously declared `httpx` only. It now also declares `httpx2>=2.0.0`, Starlette's documented preferred transport, while retaining `httpx` for compatibility with older supported Starlette resolutions. No major dependency upgrade or application behavior change was made.
- The local test environment was not modified outside the project to install packages, so the warning remains until the updated development requirements are installed. Starlette documents the `httpx2` preference at [Starlette TestClient documentation](https://www.starlette.io/testclient/).

## Files modified and new

Direct PHASE 26.2 edits:

- `database/repositories.py`, `bot/middleware.py`, `services/monitoring.py`, `services/trade_executor.py` — prevent raw database/provider/handler exception messages and tracebacks from entering active logs.
- `requirements-dev.txt` — declare Starlette's preferred `httpx2` TestClient transport.
- `tests/test_credentials_security.py` — add a regression test for database exception-log redaction.

New file created in this phase:

- `artifacts/PHASE26_2_FINAL_HARDENING_REPORT.md` — this report.

The worktree also contains PHASE 26.1 changes shown in the final Git status below; they were not reimplemented in this review.

## Integrity and Git

- Baseline inventory: 154 paths; missing baseline paths: **0**. Files deleted: **0**.
- Current file inventory: 160 excluding Git/cache data. Six paths are outside the baseline inventory: the Phase 26 preparation, Phase 26.1 hardening, and Phase 26.2 reports; two Phase 26.1 test files; and `web/cors.py`.
- No tests or migrations were deleted. No `.env` was created. No remote or push was used. No commit was made after baseline `eb90c8e`.
- Final `git diff --check`: passed.
- `git diff --stat` reports tracked-file changes only; untracked report/tests/helper files are not included in that stat.
- Final `git status --short` and `git diff --stat` snapshots:

```text
 M .env.example
 M bot/admin.py
 M bot/callbacks.py
 M bot/main.py
 M bot/message_utils.py
 M bot/middleware.py
 M bot/registration.py
 M bot/settings.py
 M bot/trading.py
 M config/settings.py
 M core/models.py
 M database/database.py
 M database/db_persistence.py
 M database/models.py
 M database/repositories.py
 M database/utils.py
 M gateway_client/adapter.py
 M requirements-dev.txt
 M services/auth.py
 M services/cache.py
 M services/monitoring.py
 M services/notification.py
 M services/payment.py
 M services/queue.py
 M services/subscription.py
 M services/trade_executor.py
 M web/api/dashboard.py
 M web/api/mt5.py
 M web/api/webhooks.py
 M web/app.py
 M web/runtime.py
?? artifacts/PHASE26_2_FINAL_HARDENING_REPORT.md
?? artifacts/PHASE26_HARDENING_REPORT.md
?? tests/test_cors_policy.py
?? tests/test_credentials_security.py
?? web/cors.py
```

```text
31 files changed, 317 insertions(+), 216 deletions(-)
```

The diff stat covers tracked files only; the report and other untracked Phase 26 artifacts are shown in `git status` and are not included in the stat.

## Remaining warnings and production blockers

1. Plaintext storage remains for `gateway_api_key` and `user_settings.api_key`, and legacy models can hold additional plaintext-capable credentials.
2. Historical bot persistence rows and deployed DB rows were not read or scrubbed. Existing secrets must be inventoried and remediated safely.
3. No encryption-key versioning, backup, or rotation process exists. Losing/changing a deployed key can make old ciphertext unrecoverable.
4. PostgreSQL runtime migration execution and deployed-schema compatibility have not been verified.
5. The active environment still emits one Starlette/httpx deprecation until `httpx2` is installed from updated dev dependencies.
6. The unused `bot/main_backup.py` retains raw exception logs; it is not imported by the current entry point, but should not be used for deployment.

## Phase 27 recommendations

- Decide the credential ownership model, encryption boundary, key provider, key versioning and rotation/recovery policy before designing a migration.
- Plan a data-safe migration for gateway/API credentials: encrypt recoverable credentials with versioned keys or store only a hash where verification is sufficient; preserve an explicit, audited rotation/revocation path.
- Inventory and remediate legacy MT5/MetaAPI fields and historical `bot_persistence_store` values without printing or exporting secret values.
- Add a disposable PostgreSQL migration verification job for revisions 001–016 and supported upgrade states; compare Alembic output/schema with current SQLAlchemy models. Do not downgrade 015.
- Install dev dependencies from `requirements-dev.txt` in the project’s normal isolated developer environment and rerun tests to confirm `httpx2` removes the warning.

## Decisions that must not be automatic

- Whether gateway API credentials remain locally recoverable or are only held by the gateway.
- Encryption-at-rest schema design, KMS/secret-manager choice, key backup/rotation and failure-recovery behavior.
- Whether API tokens are replaced by one-way hashes and how existing users rotate/recover them.
- Cleanup/removal of legacy columns and existing stored values; this requires data-retention, migration, and recovery decisions.
- Any PostgreSQL production migration, rollback, or destructive data operation.
