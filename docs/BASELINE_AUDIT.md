# TONPO Bot Baseline Audit

**تاريخ الفحص:** 2026-10-10
**الفرع:** `chore/standardize-runtime-versions`
**نطاق الفحص:** نسخة Git من `ahbhdjbfjbc/tonpo-bot`، مع قراءة الكود والإعدادات والاختبارات والتقارير السابقة.

## البنية والتدفق

المشروع Python/Telegram مع FastAPI/Web UI وPostgreSQL وRedis وTonpo SDK. المسار المعلن حاليًا هو:

`TradingView webhook أو Telegram signal → SignalPipeline → auth/subscription/news/risk/idempotency → TradeExecutor → ExecutionProvider → Gateway adapter → Tonpo SDK → Gateway خارجي → MT5`.

نقطة منع التنفيذ الحالية في `TradeExecutor` تشمل `TRADING_DRY_RUN`، جاهزية schema، positions، quote، ثم `get_symbol_constraints()`؛ محول Tonpo الحالي يرفض مواصفات الرمز لأن SDK 1.0.4 لا يثبت وجود هذا العقد.

## التخزين والعلاقات

`User` يخزن Telegram identity وحالة الحساب وgateway references. `Trade` مرتبط بـ `user_id` ويحتوي `mt_order_ids` و`execution_results` وstatus. توجد migrations حتى 022 تقريبًا. محول Gateway الحالي يحتفظ بمفاتيح واتصالات في قواميس process-local، مع تحميل من DB، وهذا لا يكفي وحده لعزل محركات MetaDocker أو provisioning متعدد العملاء.

## التشغيل

- `main.py`: تشغيل البوت.
- `python -m web.run`: تشغيل FastAPI/Web.
- `docker-compose.yml`: PostgreSQL وRedis وbot وweb.
- Alembic: `database/migrations`.
- worker/queue paths موجودة في `services/queue.py` لكن لم يُثبت تشغيل worker خارجي في هذا الفحص.

## النتائج الفعلية

| البند | الحالة | الدليل |
|---|---|---|
| صياغة Python | PASS | `python -m compileall -q bot config core database gateway_client services utils web main.py`، exit 0 |
| جمع الاختبارات | PASS | `python -m pytest --collect-only -q`، exit 0 |
| الاختبارات | FAIL | `python -m pytest -q --disable-warnings`؛ فشل `tests/test_guest_mode.py::test_assistant_allows_public_guidance_but_uses_optional_account_context` |
| CI dependency install | PASS بعد إصلاح | تعارض `pylint 3.3.0`/`isort 6.0.1` عولج بـ `isort 5.13.2` |
| MetaDocker runtime | BLOCKED | لا توجد خدمة أو حساب MT5 Demo أو API key |
| E2E TradingView → MT5 | NOT TESTED | لا توجد بيئة Engine/Broker تجريبية |
| عزل حسابين | NOT TESTED | لا توجد مثيلات MetaDocker وحسابان Demo |
| Migrations على PostgreSQL فعلي | NOT TESTED | لا توجد قاعدة PostgreSQL runtime متاحة في الفحص |

## المشكلة الاختبارية الحالية

`web/api/assistant.py` يستورد ويستخدم `get_current_user` لمسار `/chat`، بينما الاختبار يرفض ظهور هذا الاسم في الملف ويطلب guest guidance. هذا تعارض سلوكي/اختباري يحتاج قرارًا أمنيًا موثقًا؛ لم يتم إضعاف المصادقة لإرضاء الاختبار.

## قيود وموانع الإطلاق

- MetaDocker وMT5/Broker demo غير متوفرين.
- لا يوجد إثبات تنفيذ أو إغلاق أو reconciliation.
- الاختبارات الأساسية ليست خضراء.
- جودة Flake8/Mypy تحتوي مخالفات قديمة، ولذلك هي advisory في CI حاليًا.
- التداول الحقيقي يجب أن يبقى معطلاً.
