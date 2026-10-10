# Test Results

## Baseline run — 2026-10-10

| الأمر | الحالة | النتيجة |
|---|---|---|
| `python -m compileall -q bot config core database gateway_client services utils web main.py` | PASS | exit 0 |
| `python -m pytest --collect-only -q` | PASS | exit 0 |
| `python -m pytest -q --disable-warnings` | FAIL | فشل اختبار guest mode واحد متعلق بـ `get_current_user` |
| `python -m coverage run --source=bot,config,core,database,gateway_client,services,utils,web -m pytest -q` | FAIL | الاختبار نفسه فشل؛ لا تُستخدم التغطية كشهادة نجاح |
| `python -m flake8 bot config core database gateway_client services utils web main.py` | FAIL / ADVISORY | مخالفات legacy كثيرة، معظمها line length وunused imports |
| `python -m mypy bot config core database gateway_client services utils web main.py` | FAIL / ADVISORY | فشل التحقق الحالي ويحتاج ضبط نطاق/أخطاء typing |
| `git diff --check` | PASS | exit 0 |

## CI

أضيف `.github/workflows/ci.yml` ويشغل Python 3.12 وcompileall وpytest وcoverage، مع Flake8/Mypy كفحوص advisory مؤقتة. لا يوجد deploy تلقائي ولا اتصال بخدمات التداول.

## غير مختبر

MetaDocker الحقيقي، MT5 terminal، broker Demo، TradingView live webhook، reconciliation الخارجي، حسابان معزولان، migrations على PostgreSQL runtime، واختبار الضغط.
