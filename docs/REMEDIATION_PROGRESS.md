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
- جعل اختيار `ENGINE_PROVIDER=metadocker` موحدًا في bot وweb، مع إيقاف تسجيل Tonpo القديم برسالة صريحة بدل ادعاء ربط MetaDocker.
- إضافة outbox retry/reclaimer لقناة النتائج: الصفوف الفاشلة أو العالقة يمكن أن يعيدها bot worker دون إعادة تنفيذ الصفقة.
- فرض حد `max_connections` عند ربط محركات MT5، و`api_access` عند تسجيل الدخول بمفتاح API.
- إصلاح downgrade ليحفظ حالة الخطة والميزات في transaction واحدة، وتمديد الاشتراك من نهاية الصلاحية الحالية بدل فقدان الأيام.
- إصلاح مسار callback لإغلاق الصفقات باستخدام provider المحقون بدل إنشاء executor بلا provider.
- تقوية consecutive-loss protection بعزل `user_id` والتحقق من قيم الحدود غير الصالحة.
- تنفيذ إعادة حساب معاينة المخاطرة في `adjust_risk` دون حفظ تفضيل مؤقت بالخطأ.
- تطبيق تفضيلات `notify_on_trade` و`notify_on_error` قبل الإرسال.
- فرض `max_symbols` وتحقق صيغة الرموز في تحديثات إعدادات الويب.
- إضافة security headers أساسية للواجهة، مع HSTS عند HTTPS.
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
- تنفيذ تدوير الأسرار في بيئة النشر الفعلية؛ لا يمكن تدوير أسرار غير موجودة في هذه البيئة دون صلاحية حسابات النشر.

### P1

- توحيد تسجيل Telegram مع `EngineInstance` أو فصل مسار Tonpo القديم بوضوح. تم تنفيذ الفصل الصريح مؤقتًا؛ الربط الكامل للمستخدم يتم عبر Web API مع health-check.
- إضافة outbox worker/retry/reclaimer لقناة النتائج. تم تنفيذ worker داخل bot، وما زال اختبار Telegram/DB حيًا مطلوبًا.
- إضافة reconciliation لنتائج `UNKNOWN` وعمليات timeout.
- إكمال فرض entitlements للاشتراك.
- إكمال enforcement المتبقي لـ`max_symbols` بعد تحديد كيان الاشتراك بالرموز في المنتج.
- إضافة login throttling عبر طبقة HTTP لا تكسر استدعاءات الاختبارات المباشرة، ثم إضافة revocation/refresh rotation.
- تقوية مصادقة الويب وتخزين الرموز.
- إضافة E2E حقيقي مع MetaDocker/MT5/Telegram/TradingView.
