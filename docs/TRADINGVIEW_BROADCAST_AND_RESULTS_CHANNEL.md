# مسار البوت المطلوب: TradingView → المشتركون → MT5 → قناة النتائج

## الهدف

- المستخدم يربط حساب MT5 الخاص به مرة واحدة.
- TradingView يرسل توصية واحدة إلى Webhook محمي.
- البوت يتحقق من الإشارة والمخاطر والاشتراك لكل مستخدم على حدة.
- المستخدم الذي وضعه `auto` ولديه ميزة التداول الآلي ينفذ تلقائيًا.
- المستخدم `semi_auto` يحصل على طلب تأكيد.
- المستخدم `manual` يحصل على الإشارة للمراجعة والتنفيذ اليدوي.
- كل تنفيذ فعلي ناجح يُنشر مرة واحدة في قناة نتائج ثانية بدون كشف هوية المستخدم أو بيانات حسابه.

## الإعدادات

```env
ENABLE_WEBHOOKS=true
TRADINGVIEW_WEBHOOK_SECRET=<secret-from-secret-manager>
TRADINGVIEW_BROADCAST_TO_SUBSCRIBERS=true
TRADE_RESULTS_CHANNEL_ID=-1001234567890
TRADING_DRY_RUN=true
ENGINE_PROVIDER=metadocker
```

`TRADINGVIEW_TELEGRAM_ID` يبقى فقط للتوافق مع التشغيل القديم ذي المستخدم الواحد عندما يكون البث الجماعي معطلًا.

## تدفق TradingView

1. TradingView يرسل `POST /api/webhooks/tradingview` مع `X-TradingView-Secret`.
2. يتم تطبيق rate limit والتحقق من timestamp وsymbol وsignal ID.
3. عند تفعيل `TRADINGVIEW_BROADCAST_TO_SUBSCRIBERS`، يختار الخادم المستخدمين:
   - active
   - verified
   - غير محظورين
   - اشتراكهم غير مجاني وغير منتهٍ
4. تُنشأ `UnifiedSignal` منفصلة لكل مستخدم؛ لذلك تبقى idempotency والعزلة لكل مستخدم.
5. `SignalPipeline` يطبق لكل مستخدم:
   - حماية الأخبار
   - حدود المخاطر
   - حدود الاشتراك اليومية
   - trade mode
   - وجود اتصال MT5
6. لا تعتمد الهوية على payload القادم من TradingView.

## أوضاع التنفيذ

| الوضع | النتيجة |
|---|---|
| `auto` | تنفيذ تلقائي إذا كانت خطة المستخدم تدعم `auto_trading` |
| `semi_auto` | إرسال زر تأكيد للمستخدم قبل التنفيذ |
| `manual` | إبقاء الإشارة في مراجعة يدوية |

التنفيذ اليدوي الحالي يمر من نفس `SignalPipeline` ولا يملك مسارًا يتجاوز المخاطر أو الاشتراك.

## قناة النتائج

بعد أن تصبح النتيجة `executed` فعلًا، وليس `dry_run` أو `pending` أو `unknown`:

1. يسجل النظام صفًا في `trade_channel_publications`.
2. يضعه في حالة `publishing` قبل الاتصال بـ Telegram.
3. يرسل ملخصًا للقناة مثل:

```text
✅ تنفيذ صفقة

Buy EURUSD
الحجم: 0.10
الدخول: MARKET
وقف الخسارة: 1.09000
الأهداف: 1.12000
```

4. عند النجاح يخزن Telegram `message_id` وحالة `published`.
5. عند الفشل يخزن `failed` واسم نوع الخطأ لإعادة المحاولة لاحقًا.
6. لا يتضمن المنشور `telegram_id` أو مفتاح API أو كلمة مرور MT5 أو اسم الحساب.

المفتاح الفريد على `signal_receipt_id` يمنع نشر الصفقة نفسها مرتين.

## تشغيل آمن

قبل أي تشغيل فعلي:

```bash
alembic upgrade head
```

ثم يجب اختبار:

- مستخدمين مشتركين بحسابي MT5 Demo منفصلين.
- مستخدم مجاني لا يحصل على تنفيذ.
- مستخدم `semi_auto` لا ينفذ قبل التأكيد.
- إعادة إرسال نفس `signal_id` لا تفتح صفقة ثانية.
- timeout لا يعيد إرسال أمر التداول تلقائيًا.
- فشل Telegram لا يغيّر نتيجة الصفقة لدى الوسيط.

لا يُسمح بتغيير `TRADING_DRY_RUN=false` قبل اجتياز هذه الاختبارات على Demo.
