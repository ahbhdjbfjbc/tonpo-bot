# MetaDocker MT5 Engine Integration

## حالة التحقق

**الحالة: VERIFIED / MOCKED ADAPTER INTEGRATED / LIVE DEMO BLOCKED**

تمت مراجعة المستودع الرسمي عند:

- الإصدار: `v1.0.1`
- commit: `dfc44a3826a8fdb8fc93c78d546ceb10c0041d65`
- الترخيص: MIT
- Python requirement: `>=3.10`
- المستودع: https://github.com/marketcalls/meta-docker

## ما ثبت من المصدر الرسمي

MetaDocker يضع REST/WebSocket/gRPC أمام طرفية MetaTrader 5. الواجهة تشمل `/health` و`/account` و`/terminal` و`/symbols/{symbol}` و`/symbols/{symbol}/tick` و`/positions` و`/orders` و`/history/orders` و`/history/deals` و`/orders/market` و`/orders/check` و`/orders/send` و`/positions/{ticket}/close`.

المصادقة الافتراضية عبر `X-API-Key`، والمفتاح مخزن كـ SHA-256 digest. الوضع `BRIDGE_READ_ONLY=1` يمنع أوامر التداول. المنافذ يجب أن تبقى على loopback أو شبكة خاصة، ولا يجوز نشر 8001 مباشرة للإنترنت.

الأهم لتصميم TONPO: الوثائق تقول صراحة إن **كل Bridge يربط طرفية واحدة وحسابًا واحدًا**. الحساب الثاني يحتاج مثيلًا/حاوية أخرى، وليس مجرد API key آخر.

## حقول التنفيذ التي يجب احترامها

- `/orders/market` يعيد `retcode`, `deal`, `order`, `volume`, `price`, `comment`, و`request`.
- `retcode=10009` يعني تنفيذًا ناجحًا حسب الوثيقة، بينما 10027 يدل على تعطيل Algo Trading و10019 على insufficient funds و10018 على market closed و10030 على unsupported filling.
- لا يجوز مساواة `order` بـ `deal` أو `position ticket`.
- `/health` يعرض `connected` و`session`؛ تغير session يدل على إعادة اتصال وفجوة بيانات محتملة.

## التصميم المقترح

1. إنشاء interface داخلية مستقلة مثل `MT5EngineConnection`.
2. كتابة `MetaDockerConnectionAdapter` يستعمل HTTP client بمهلات وحدود body واضحة.
3. تحويل `account`, `symbol_info`, `tick`, `positions`, `orders`, `history`, وtrade result إلى نماذج داخلية صريحة.
4. رفض التنفيذ عند نقص `volume_min/max/step` أو `tick_size/value` أو السعر الحديث.
5. عند timeout بعد الإرسال: الحالة `UNKNOWN`، ولا إعادة إرسال تلقائية؛ يلزم reconciliation عبر history/positions.
6. فصل provisioning عن Web/API. لا Docker socket في التطبيق.
7. حفظ `engine_instance_id`, account reference, key reference, engine version, health state، وprovision state دائمًا في قاعدة البيانات.

## ما تم تنفيذه محليًا

- `gateway_client/metadocker.py` يعزل HTTP عن منطق المخاطر.
- `MetaDockerExecutionProvider` يقرأ `engine_instances` من قاعدة البيانات لكل `telegram_id`.
- `EngineInstanceRepository` يمنع امتلاك نفس engine instance من مستخدمين مختلفين.
- اختبارات mocked تغطي account/symbol/tick/positions/retcodes/timeout وفصل IDs.

## ما لم يُختبر

لم يتم تشغيل MetaDocker، ولم تتوفر MT5 terminal أو broker demo أو API key. لذلك لا يوجد إثبات اتصال أو تنفيذ أو إغلاق صفقة، ولا يجوز وصف الدمج بأنه مكتمل.

## مصادر

- https://github.com/marketcalls/meta-docker/tree/v1.0.1
- https://github.com/marketcalls/meta-docker/blob/dfc44a3826a8fdb8fc93c78d546ceb10c0041d65/docs/API.md
- https://github.com/marketcalls/meta-docker/blob/dfc44a3826a8fdb8fc93c78d546ceb10c0041d65/SECURITY.md
- https://github.com/marketcalls/meta-docker/blob/dfc44a3826a8fdb8fc93c78d546ceb10c0041d65/LICENSE
