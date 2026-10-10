# Test Results

## Baseline run — 2026-10-10

| الأمر | الحالة | النتيجة |
|---|---|---|
| `python -m compileall -q bot config core database gateway_client services utils web main.py` | PASS | exit 0 |
| `python -m pytest --collect-only -q` | PASS | exit 0 |
| `python -m pytest -q --disable-warnings` | PASS | 236 اختبارًا ناجحًا |
| `python -m pytest -q tests/test_metadocker_adapter.py tests/test_engine_instance_repository.py` | PASS | اختبارات adapter والملكية متعددة المستخدمين ناجحة |
| `python -m pytest -q tests/test_trade_channel_publication.py tests/test_tradingview_broadcast.py` | PASS | بث المشتركين وoutbox قناة النتائج idempotent |
| `python -m coverage run --source=bot,config,core,database,gateway_client,services,utils,web -m pytest -q` | PASS | التشغيل المحلي ناجح؛ لا يثبت اتصال MT5 الحقيقي |
| `python -m flake8 bot config core database gateway_client services utils web main.py` | FAIL / ADVISORY | مخالفات legacy كثيرة، معظمها line length وunused imports |
| `python -m mypy bot config core database gateway_client services utils web main.py` | FAIL / ADVISORY | فشل التحقق الحالي ويحتاج ضبط نطاق/أخطاء typing |
| `git diff --check` | PASS | exit 0 |

## CI

أضيف `.github/workflows/ci.yml` ويشغل Python 3.12 وcompileall وpytest وcoverage، مع Flake8/Mypy كفحوص advisory مؤقتة. لا يوجد deploy تلقائي ولا اتصال بخدمات التداول.

أضيفت migration `023_add_engine_instances`، لكن لم تُشغّل بعد على PostgreSQL runtime حقيقي في هذه البيئة.

## غير مختبر

MetaDocker الحقيقي، MT5 terminal، broker Demo، TradingView live webhook، reconciliation الخارجي، حسابان Demo فعليان، migrations على PostgreSQL runtime، واختبار الضغط.

لم يتم تشغيل broadcast الحي أو النشر إلى قناة Telegram حقيقية؛ الاختبار الحالي يستخدم SQLite وTelegram mock.


## Current remediation branch run — 2026-10-10

| الفحص | الحالة | النتيجة |
|---|---|---|
| `./.venv/bin/pytest --disable-warnings --tb=short tests/` | PASS | **299 passed, 300 warnings** في 14.62 ثانية؛ التحذيرات تشمل datetime legacy وتحذيرات تبعيات |
| `./.venv/bin/alembic heads` | PASS | رأس واحد: `025_system_metrics_schema_alignment` |
| `alembic upgrade head --sql` على PostgreSQL | PASS | توليد SQL لكل السلسلة حتى revision 025 |
| اختبار migration 025 على SQLite legacy schema | PASS | backfill، `created_at NOT NULL`، تبديل الفهارس، واختبار downgrade العكسي |
| backup/restore smoke باستخدام GPG الحقيقي وstubs لأوامر PostgreSQL | PASS | تشفير/فك تشفير، checksum بعد النقل، permissions، إخفاء URLs عن العمليات التابعة، ورفض قاعدة غير فارغة |
| `bash -n` و`git diff --check` | PASS | لا أخطاء صياغة أو whitespace |

**قيد مهم:** لم تتوفر أدوات `pg_dump`/`pg_restore` أو PostgreSQL runtime في هذه البيئة؛ smoke backup/restore لا يثبت الاستعادة من قاعدة فعلية. كما لم تُختبر خدمات PostgreSQL/Redis وMetaDocker/MT5/Telegram الحية أو ضغط الإنتاج. لا تُفعّل التداول الحي قبل إنجاز بوابات staging والنسخ الخارجية الواردة في runbook.
