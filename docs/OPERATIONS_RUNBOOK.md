# Operations Runbook — Safe Development

## التشغيل المحلي

1. استخدم Python 3.12.
2. انسخ `.env.example` إلى `.env` واستبدل placeholders محليًا فقط.
3. شغّل PostgreSQL 16 وRedis 7.
4. نفّذ `make migrate` على قاعدة غير إنتاجية.
5. تحقق من `TRADING_DRY_RUN=true`.
6. شغّل البوت عبر `make run` والويب عبر `python -m web.run` عند الحاجة.

## Compose

`docker-compose.yml` يستخدم PostgreSQL 16 وRedis 7. كلمة `POSTGRES_PASSWORD` مطلوبة. الخدمات تتصل بـ `postgres` داخليًا، ولا ينبغي نشر قاعدة البيانات أو MetaDocker للعامة.

## التعافي

عند توقف Gateway/Engine أو timeout في أمر: لا تعاود الإرسال تلقائيًا. سجّل `UNKNOWN`، افحص history/positions، ثم نفّذ reconciliation. لا تحذف بيانات الحالة قبل حفظ نسخة واستكمال التحقيق.

## MetaDocker المستقبلي

ابدأ بـ `BRIDGE_READ_ONLY=1`، loopback/private network، volume دائم، وحساب Demo. شغّل مثيلًا منفصلًا لكل حساب حتى يثبت تصميم provisioning وعزل البيانات.

## غير متاح حاليًا

لا توجد تعليمات تشغيل فعلية لـ MetaDocker داخل البيئة الحالية لأن Engine وMT5 وDemo account غير متوفرين.
