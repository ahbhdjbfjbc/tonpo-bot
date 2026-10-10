# سجل تنفيذ الإصلاحات

## القاعدة

هذه الوثيقة تسجل إصلاحات تم تنفيذها والتحقق منها فقط. لا تعتبر الاختبارات المحلية أو mocks دليلًا على اتصال حي بوسيط أو MetaDocker.

## المرحلة P0 — منفذة في نسخة العمل

- إصلاح تمرير `execution_provider` إلى `TradingHandler.trade_executor` في مسار البوت.
- فرض وضع حساب `live` قبل أي تنفيذ حقيقي داخل `SignalPipeline` و`TradeExecutor`.
- فرض `ENABLE_AUTO_TRADING` قبل قبول الوضع `auto`.
- إضافة `user_id` إلى بحث إغلاق الصفقة.
- إضافة حالة `closed` إلى حالات `Trade` الرسمية.
- جعل قيود slippage وvolatility fail-closed عند غياب القياس.
- إضافة سياسة MetaDocker: HTTPS افتراضيًا، allowlist اختيارية، ورفض العناوين العامة غير الموثوقة.
- تنفيذ health-check لـMetaDocker قبل حفظ الربط.
- إبطال cache الاتصال عند تغيير endpoint/key أو تعطيل المحرك.
- إضافة `/api/live` و`/api/ready`؛ readiness يفحص DB وAlembic schema وRedis.
- إضافة خدمة `tonpo-migrate` إلى Compose وجعل bot/web يعتمدان على نجاح `alembic upgrade head`.
- ربط منافذ PostgreSQL وRedis على `127.0.0.1` بدل النشر العام.
- إزالة archive متتبع يحتوي `.env` و`.git`؛ هذا إجراء أمني، وليس حذفًا لميزة تطبيق.

## تحقق P0

- `compileall`: ناجح.
- تحليل Compose YAML: ناجح.
- الاختبارات المركزة: ناجحة.
- مجموعة الاختبارات الكاملة: ناجحة.
- `git diff --check`: ناجح.
- لم يتم اختبار MetaDocker أو MT5 أو PostgreSQL/Redis فعليًا في هذه البيئة؛ لذلك لا يوجد ادعاء بذلك.

## المتبقي

### P0 إضافي قبل التداول الحقيقي

- تدوير الأسرار التي كانت داخل archive وفق بيئة النشر الفعلية.
- تشغيل PostgreSQL/Redis وAlembic في staging والتحقق من fresh install وupgrade.
- اختبار متعدد المستخدمين مع حسابات MT5 Demo منفصلة.

### P1

- توحيد تسجيل Telegram مع `EngineInstance` أو فصل مسار Tonpo القديم بوضوح.
- إضافة outbox worker/retry/reclaimer لقناة النتائج.
- إضافة reconciliation لنتائج `UNKNOWN` وعمليات timeout.
- إكمال فرض entitlements للاشتراك.
- تقوية مصادقة الويب وتخزين الرموز.
- إضافة E2E حقيقي مع MetaDocker/MT5/Telegram/TradingView.
