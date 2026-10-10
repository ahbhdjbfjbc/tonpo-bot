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
