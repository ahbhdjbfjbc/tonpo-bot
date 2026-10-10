# Test Results

## Baseline run — 2026-10-10

| الأمر | الحالة | النتيجة |
|---|---|---|
| `python -m compileall -q bot config core database gateway_client services utils web main.py` | PASS | exit 0 |
| `python -m pytest --collect-only -q` | PASS | exit 0 |
| `python -m pytest -q --disable-warnings` | PASS | 236 اختبارًا ناجحًا |
| `python -m pytest -q tests/test_metadocker_adapter.py tests/test_engine_instance_repository.py` | PASS | اختبارات adapter والملكية متعددة المستخدمين ناجحة |
| `python -m coverage run --source=bot,config,core,database,gateway_client,services,utils,web -m pytest -q` | PASS | التشغيل المحلي ناجح؛ لا يثبت اتصال MT5 الحقيقي |
| `python -m flake8 bot config core database gateway_client services utils web main.py` | FAIL / ADVISORY | مخالفات legacy كثيرة، معظمها line length وunused imports |
| `python -m mypy bot config core database gateway_client services utils web main.py` | FAIL / ADVISORY | فشل التحقق الحالي ويحتاج ضبط نطاق/أخطاء typing |
| `git diff --check` | PASS | exit 0 |

## CI

أضيف `.github/workflows/ci.yml` ويشغل Python 3.12 وcompileall وpytest وcoverage، مع Flake8/Mypy كفحوص advisory مؤقتة. لا يوجد deploy تلقائي ولا اتصال بخدمات التداول.

أضيفت migration `023_add_engine_instances`، لكن لم تُشغّل بعد على PostgreSQL runtime حقيقي في هذه البيئة.

## غير مختبر

MetaDocker الحقيقي، MT5 terminal، broker Demo، TradingView live webhook، reconciliation الخارجي، حسابان Demo فعليان، migrations على PostgreSQL runtime، واختبار الضغط.
