# TradingView Webhook Setup

## الحالة

المسار البرمجي موجود في `web/api/webhooks.py` ويمر إلى `SignalPipeline`، لكن لم يُختبر إرسال Webhook حي من TradingView في هذه البيئة. الحالة: **NOT TESTED**.

## متطلبات قبل الاعتماد

- body محدود الحجم وContent-Type JSON.
- سر/توقيع موثق ومطابق لطريقة TradingView الفعلية.
- timestamp حديث وsignal ID فريد.
- symbol وside وorder type وSL/TP صالحة.
- idempotency key دائم بقيد قاعدة بيانات فريد ضمن نطاق المستخدم/الاستراتيجية/الحساب.
- استجابة سريعة بعد حفظ الإشارة أو وضعها في queue؛ لا تنتظر تنفيذًا طويلًا داخل request.

## مثال آمن بلا أسرار

```json
{
  "signal_id": "demo-signal-001",
  "symbol": "EURUSD",
  "side": "buy",
  "order_type": "market",
  "entry": "NOW",
  "sl": 1.09000,
  "tp": 1.10000,
  "timestamp": "2026-01-01T12:00:00Z"
}
```

هذا المثال توضيحي فقط وليس إثباتًا لتوافق TradingView. لا تستخدم `user_id` القادم من payload لتحديد حساب؛ يجب أن يأتي الربط من تكامل موثوق محفوظ دائمًا.

## اختبارات مطلوبة

Payload ناقص/مشوه/كبير، سر خاطئ، replay، signal ID مكرر، timestamp قديم، symbol غير معروف، order type غير مدعوم، اشتراك منتهٍ، ومحاولة الوصول إلى حساب مستخدم آخر.

## إعداد تنبيه TradingView الفعلي

TradingView لا يسمح بإضافة Headers مخصصة للطلب، ويرسل نص رسالة التنبيه فقط. لذلك يقبل الخادم كلمة السر داخل JSON في الحقل `secret`. يبقى الـ Header `X-TradingView-Secret` مدعومًا للتكاملات الأخرى، وله الأولوية إذا أُرسل.

- Webhook URL: `https://<your-domain>/api/webhooks/tradingview` (يقبل TradingView المنفذين 80 و443 فقط، ولا يدعم IPv6).
- في `.env`: `ENABLE_WEBHOOKS=true`، و`TRADINGVIEW_WEBHOOK_SECRET=<قيمة عشوائية طويلة>`، و`TRADINGVIEW_TELEGRAM_ID=<معرّف تيليجرام للحساب المستهدف>`، و`TRADINGVIEW_SYMBOL_MAP={"EURUSD":"EURUSD"}`.
- ضع في حقل Message للتنبيه:

```json
{
  "secret": "PASTE_TRADINGVIEW_WEBHOOK_SECRET",
  "id": "{{ticker}}-{{interval}}-{{timenow}}",
  "symbol": "{{ticker}}",
  "action": "{{strategy.order.action}}",
  "stop_loss": 1.0500,
  "take_profit": 1.1000,
  "timestamp": "{{timenow}}"
}
```

يُحذف حقل `secret` قبل التحقق من صحة الإشارة، ولا يُحفظ ولا يُسجَّل.

نتيجة الاختبار الحي على خادم محلي بوضع `TRADING_DRY_RUN=true`: الإشارة الصحيحة قُبلت وحُفظت. ورُفضت الحالات التالية برموز الاستجابة الموضحة:

- تكرار المعرّف نفسه: 409.
- كلمة سر خاطئة: 401.
- توقيت قديم: 400.
- رمز غير معرّف: 400.
- حقل `user_id` داخل الطلب: 400.
