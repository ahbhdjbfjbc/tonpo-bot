# تقرير تدقيق الميزات — Tonpo Bot

**نوع التقرير:** مراجعة رئيسية متعددة الميزات

**نطاق التدقيق:** مراجعة نتائج التدقيق المقدمة، الأدلة البرمجية المشار إليها، الاختبارات المذكورة، ومسارات التشغيل الموثقة. لم يُجرَ تعديل على كود التطبيق، ولم تُعتبر الاختبارات الخضراء دليلًا على تكامل خارجي حقيقي.

**حالة عناصر الفشل المسجلة:** `[]` — لم تُسجّل عناصر فشل مستقلة خارج العيوب والفجوات الواردة في نتائج تدقيق الميزات.

---

## 1. الملخص التنفيذي

المنتج يحتوي على قدر كبير من البنية البرمجية الموصولة فعليًا: FastAPI وTelegram handlers، نماذج وقواعد بيانات وAlembic، SignalPipeline، إدارة الاشتراكات والدفع اليدوي، طبقة حماية ومخاطر، واجهة ويب، ومحول MetaDocker نظريًا. كما أن الاختبارات المحلية المركزة تمر غالبًا، و`compileall` ينجح، وتوجد مؤشرات جيدة على العزل، منع التكرار، تشفير بعض المفاتيح، والتصميم fail-closed في أجزاء مهمة.

لكن **الجاهزية التشغيلية والتكاملية غير مثبتة، وبعض المسارات الأساسية معطلة فعليًا**:

1. **تكامل تسجيل Telegram مع MT5/MetaDocker مكسور في الإعداد الافتراضي:** عند `TRADING_DRY_RUN=true` لا تتم تهيئة المزود، فيفشل `/register` برسالة `Gateway not initialised`. وحتى عند تعطيل dry-run، يستخدم التسجيل مزود Tonpo القديم ويحفظ حقول `users.gateway_*` ولا ينشئ `EngineInstance` الذي يحتاجه مسار MetaDocker.
2. **تنفيذ البوت اليدوي/القناة مكسور عند التشغيل الحي:** يتم حقن المزود في `TradingHandler` فقط، لا في `self.trading.trade_executor` الذي يستعمله المسار الفعلي، ولذلك قد ينتهي التنفيذ إلى `No execution provider` قبل الوصول إلى الوسيط.
3. **الاستقبال الخارجي والتداول الحي غير مثبتين:** `ENABLE_WEBHOOKS=false` و`TRADING_DRY_RUN=true` افتراضيًا، ولا توجد بيئة TradingView/Telegram/Gateway/MetaDocker/MT5 حقيقية أو دليل E2E حي.
4. **مخاطر أمنية وتشغيلية عالية:** endpoint محرك MT5 يقبل عنوانًا يقدمه المستخدم دون سياسة allowlist/شبكة خاصة ظاهرة، ما يثير خطر SSRF؛ تخزين JWT في `localStorage` وWebSocket query string يزيد خطر التسريب؛ ولا يوجد rate limit لمسار تسجيل الدخول.
5. **النشر وقاعدة البيانات غير جاهزين:** Compose لا يطبق migrations قبل تشغيل البوت والويب، وhealthcheck لا يتحقق من DB/Redis/schema، ولا توجد آلية backup/restore تشغيلية. كما أن أرشيفًا متتبعًا يحتوي `.env` و`.git`، ما يستلزم اعتبار الأسرار التاريخية مكشوفة وتدويرها.
6. **الإشعارات وقناة النتائج غير مكتملة تشغيليًا:** web runtime ينشئ `NotificationService` دون Telegram bot، وفشل الإرسال يبقى `failed` بلا worker retry أو استرداد لحالة `publishing` العالقة.
7. **واجهة الويب عربية شكليًا لا وظيفيًا بالكامل:** RTL موجود، لكن كثيرًا من العناوين والحالات والرسائل إنجليزية، وإعداد اللغة يُخزّن دون طبقة i18n، مع وجود حقن `innerHTML` لقيم قادمة من الخادم دون تهريب شامل، ما يخلق خطر XSS.

**الحكم العام:** النظام **موجود جزئيًا لكنه غير جاهز للإنتاج أو التداول الحي**. الأولوية قبل أي تمكين لـ`TRADING_DRY_RUN=false` هي إصلاح حدود التنفيذ ومزود الخدمة والعزل، ثم بوابة migrations والنشر، ثم E2E حقيقي مع وسيط تجريبي، مع معالجة SSRF والأسرار وإعادة المحاولة.

---

## 2. جدول الحالة الإجمالي

| الميزة | الحالة | الحكم المختصر | مستوى الخطر |
|---|---|---|---|
| تسجيل المستخدم وربط MT5 وMetaDocker | **BROKEN** | مكونات التخزين وWeb API موجودة، لكن `/register` لا ينشئ/يحل `EngineInstance`، والإعداد الافتراضي يفشل قبل التهيئة | حرج/مرتفع |
| استقبال TradingView وقنوات Telegram وتوزيع الإشارات | **PARTIAL** | المسارات والمصادقة وSignalPipeline موجودة، لكن الاستقبال معطل افتراضيًا ولا يوجد E2E أو تنفيذ خارجي مثبت | مرتفع |
| التنفيذ اليدوي والآلي وإدارة المخاطر والحماية | **BROKEN** | الحماية والحسابات موجودة، لكن مزود التنفيذ لا يصل إلى TradeExecutor في مسار البوت، وبعض حدود mode/flags غير enforced | حرج/مرتفع |
| الاشتراكات والدفع والحدود والميزات | **PARTIAL** | الدفع اليدوي وموافقة admin تعملان محليًا، لكن UX غير مكتمل، verifier الآلي غير موجود، وبعض entitlements غير مفروضة | مرتفع |
| إشعارات المستخدمين وقناة نتائج الصفقات | **PARTIAL** | outbox وidempotency موجودان، لكن web منفصل بلا bot، ولا retry/worker أو احترام كامل للتفضيلات | مرتفع |
| واجهات الويب والمصادقة والأمان | **PARTIAL** | routers والعزل والمصادقة موجودة، لكن token handling وlogin throttling وXSS وruntime deployment فجوات إنتاجية | مرتفع |
| الإدارة والتشغيل وقاعدة البيانات والنسخ والنشر | **BLOCKED** | التشغيل المحلي والـmigrations في الشجرة موجودان، لكن deploy fresh DB وhealth وbackup/restore وPostgreSQL الفعلي غير مثبتة | حرج |

> **ملاحظة منهجية:** الحالة `BLOCKED` تعني أن التحقق التشغيلي متعذر أو غير مثبت بسبب البيئة/غياب الخدمات، ولا تعني أن كل الكود مفقود. أما `BROKEN` فتعني وجود مسار مستدل عليه من الأدلة يتعطل في التشغيل المقصود.

---

## 3. النتائج التفصيلية حسب الميزة

## 3.1 تسجيل المستخدم وربط MT5 وMetaDocker

**الحالة: BROKEN** — التخزين وWeb API والمحول موجودة، لكن التكامل الفعلي بين تسجيل Telegram وMetaDocker غير موصول، والمسار الافتراضي يفشل.

### الأدلة

- `bot/main.py:127-128` ينشئ `gateway_client.adapter.ExecutionProvider` القديم، و`bot/main.py:288-311` يهيئه خارج dry-run فقط.
- `bot/registration.py:23-37,188-197` يستخدم provider اختياريًا ويستدعي `register_user` بحقول MT5.
- `gateway_client/adapter.py:323-368,485-486` يثبت أن المسار الخارجي هو Tonpo `create_user/create_account/wait_for_active`، وأن الاستخدام دون تهيئة يعطي `Gateway not initialised`.
- `bot/registration.py:206-247` يكتب `users.gateway_*` و`mt5_account_id/mt5_server`، ولا يكتب `engine_instances`.
- `database/models.py:320-349` و`migrations/023_add_engine_instances.py:15-37` يثبتان وجود نموذج التخزين والقيود، لكن وجود schema لا يثبت أن `/register` يستخدمه.
- `web/api/mt5.py:37-140` يوفر CRUD/status/logs، و`web/runtime.py:47-59,101-109` يختار MetaDocker فقط في web runtime ويعيد عدم اتصال في dry-run.
- `gateway_client/metadocker.py:298-320` يخزن الاتصال حسب `engine_instance_id` فقط، ما يجعل تغيير endpoint/key في العملية غير مبطل للـcache القديم.
- التوثيق (`docs/BASELINE_AUDIT.md` و`docs/MT5_ENGINE_INTEGRATION.md`) يقر بعدم توفر MetaDocker/live demo وعدم تنفيذ الاختبار الحي.

### ما هو موجود

- ConversationHandler لتسجيل Telegram وإدخال الحساب وكلمة المرور والخادم والتأكيد.
- كلمة المرور تبقى في الذاكرة المؤقتة ولا تُخزن في `user_data` أو قاعدة البيانات.
- تشفير gateway API key عبر `encrypt_gateway_api_key`.
- نموذج `EngineInstance` وmigration 023، ومستودع يفرض ملكية محرك واحدة ويدعم list/active/upsert/disable.
- Web API لربط/تعطيل/list/status/logs.
- `MetaDockerConnectionAdapter` و`MetaDockerExecutionProvider` مع account/positions/price/constraints/orders وتحويل retcodes.
- اختبارات mocked لعزل الملكية وHTTP/trade/timeout والقيود.

### النواقص والأخطاء

- لا يوجد ربط فعلي بين `/register` و`EngineInstanceRepository` أو MetaDocker.
- اختيار `ENGINE_PROVIDER=metadocker` يؤثر على `web/runtime.py` فقط ولا يغير provider الذي ينشئه البوت.
- `TRADING_DRY_RUN=true` يمنع التهيئة، فيجعل التسجيل الحي يفشل في الإعداد الافتراضي.
- `PUT /api/mt5/engine` يحفظ endpoint ويجعله active دون health-check أو provisioning أو مطابقة account ownership.
- لا توجد سياسة ظاهرة لـallowlist أو private-network أو TLS قبل الاتصال، مع احتمال SSRF.
- cache اتصال MetaDocker لا يبطل تلقائيًا عند تغيير endpoint أو المفتاح أو التعطيل.
- لا توجد اختبارات مباشرة bind/list/disable/status مع dependency overrides، ولا اختبار أن التسجيل ينشئ EngineInstance ثم يحله بنفس Telegram ID.

### المخاطر

- **تشغيلي:** التسجيل ينجح ظاهريًا في المسار القديم دون أن يستطيع MetaDocker حل محرك للمستخدم.
- **أمني:** endpoint مدخل المستخدم قد يوجه التطبيق لخدمة داخلية/غير موثوقة.
- **اتساق:** عمليات لاحقة قد تستخدم عنوانًا أو مفتاحًا قديمًا من cache.
- **إطلاق خاطئ:** وجود API والنماذج قد يعطي انطباعًا زائفًا باكتمال التكامل.

### الاختبارات والأدلة التشغيلية

- نجح `compileall`.
- نجحت اختبارات adapter/repository المركزة، ومنها اختبارات MockTransport وSQLite.
- لا يوجد اتصال حقيقي بـMetaDocker أو MT5 أو broker demo.
- لم تُثبت migrations على قاعدة تشغيلية.

---

## 3.2 استقبال TradingView وقنوات Telegram وتوزيع الإشارات

**الحالة: PARTIAL** — المسارات البرمجية مربوطة فعليًا، لكن الإعداد الافتراضي والتكامل الخارجي يمنعان اعتبارها جاهزة.

### الأدلة

- `web/api/webhooks.py:24,158-225,238-265` يعرّف route TradingView، المصادقة، rate limit، حجم body، schema، timestamp، signal ID، symbol normalization، وsingle/broadcast response.
- `web/app.py:95-118` يضمّن router.
- `bot/main.py:242-278` يسجل `channel_post` ويتحقق من `TELEGRAM_SIGNAL_CHANNEL_IDS` ويبني envelopes.
- `services/signal_pipeline.py:46-273` يطبق authentication، normalization، receipt/idempotency، protection، subscription، mode، emergency stop، والتنفيذ/الإشعار.
- `database/models.py:352-378,626-660` وmigrations 011/017/019/024 توفر التخزين الدائم.
- `services/notification.py:163-236` ينفذ publication/outbox.
- الإعدادات في `config/settings.py:296-313` تجعل `ENABLE_WEBHOOKS=false` و`TRADING_DRY_RUN=true` افتراضيًا، وتترك القنوات/الهدف الخارجي غير مضبوطين.

### ما هو موجود

- ingress فعلي عبر FastAPI وليس كودًا orphan.
- HMAC server-side باستخدام `hmac.compare_digest`، وعدم أخذ هوية المستخدم من payload.
- تصفية المشتركين active/verified/non-banned ومدفوعي الاشتراك، وتمرير كل target إلى pipeline.
- handler Telegram channel_post مع allowlist.
- canonical normalization وidempotency durable عبر `SignalReceipt`.
- حماية الأخبار، limits، subscription، emergency stop، وtrade mode.
- outbox فريد لكل receipt وقناة نتائج اختيارية.

### النواقص والأخطاء

- لا يوجد E2E حقيقي مع TradingView أو Telegram API أو Gateway/MT5.
- الإعداد الافتراضي يعطل webhook والتنفيذ والبث.
- `tonpo-bot` و`tonpo-web` عمليتان منفصلتان؛ `set_runtime` لا يشارك executor أو ذاكرة بينهما.
- لا يوجد worker/cron لإعادة محاولة publications الفاشلة.
- لا توجد تغطية مباشرة كافية لـcaption/text وchannel_post الحقيقي وتوزيع عدة مستخدمين من PTB.
- الحالة الفعلية لـmigration chain على runtime غير معروفة؛ `alembic current` يتوقف عند إعدادات مفقودة.

### المخاطر

قد تبدو المسارات مكتملة بينما لا تستقبل أي traffic في الإعداد الافتراضي. وبعد تفعيلها، قد يصل signal إلى web process دون قناة Telegram أو provider حي، أو قد تبقى نتيجة مجهولة بلا reconciliation.

### الاختبارات

- نجحت اختبارات webhook/broadcast/publication/SignalPipeline وcompileall المذكورة.
- الاختبارات تستخدم `TestClient` وmocks وAsyncMock، ولا تثبت قناة أو broker حقيقيًا.
- لا توجد خدمة طويلة العمر أو إرسال خارجي فعلي ضمن التدقيق.

---

## 3.3 التنفيذ اليدوي والآلي وإدارة المخاطر والحماية

**الحالة: BROKEN** — طبقات الحماية والحساب موجودة، لكن مسار البوت الفعلي لا يمرر provider إلى executor، وحدود مهمة ليست enforcement.

### الأدلة

- `bot/main.py:80-88` ينشئ TradingHandler بلا provider، و`bot/main.py:288-319` يعيّن `self.trading.execution_provider` فقط.
- `services/trade_executor.py:32-65` يحتفظ بالprovider داخل TradeExecutor، و`_get_connection` يرجع No execution provider عند غيابه.
- `bot/trading.py:327` ومسارات `/trade` والقناة تستخدم `self.trading.trade_executor`.
- `services/signal_pipeline.py:189-273` يطبق protection/mode/subscription ثم يستدعي executor.
- `services/protection.py:133-138` يفحص consecutive losses دون `Trade.user_id == user.id`.
- `web/api/trading_mode.py:27-43` يغير تفضيلًا، بينما TradeExecutor يفحص `TRADING_DRY_RUN` العام لا demo/live لكل مستخدم.
- `web/runtime.py:33-59` يختار MetaDocker أو Tonpo بطريقة مختلفة عن البوت.
- `bot/trading.py:372-395` يحتوي `pass` في `adjust_risk`، و`bot/callbacks.py:194-220` يبني close executor بلا provider.

### ما هو موجود

- SignalPipeline موحد للتحقق والتطبيع والحماية والاشتراك وtrade mode.
- TradeExecutor يحفظ intent قبل mutation، ويميز executed/partial/unknown، ويتعامل مع timeouts دون retry تلقائي.
- RiskService يعتمد tick/volume constraints من broker.
- ProtectionService يطبق fail-closed على balance/equity/positions/daily loss/drawdown/open positions وkill switch/session/spread.
- MetaDocker adapter يتعامل مع retcodes وfreshness وconstraints.
- schema لـexecution results وrisk limits وengine instances.
- اختبارات مركزة ناجحة على dry-run، limits، MetaDocker، وphase tests.

### النواقص والأخطاء

- إصلاح wiring provider غير منفذ: provider يصل إلى handler لا إلى TradeExecutor.
- لا يوجد enforcement فعلي لـ`User.trading_mode=demo/live`؛ flag العام هو الحاجز الرئيسي.
- `ENABLE_AUTO_TRADING` لا يدخل قرار SignalPipeline بوضوح رغم وجوده في config.
- TradeExecutor المباشر لا يستدعي كل ProtectionService/NewsProtection؛ الاعتماد على pipeline يترك مسارات legacy/direct معرضة للتجاوز.
- slippage/volatility لا تغلقان عند غياب metadata رغم تفعيل الحدود.
- `pending_trades` قفل in-memory ولا يحمي بين executors/processes.
- لا يوجد reconciliation broker history/positions بعد UNKNOWN أو partial/close.
- close/modify لا يثبت P/L وclosed_at من broker history، وبعض updates لا تقيد المستخدم.
- `adjust_risk` يخبر المستخدم بالتغيير دون حفظ/إعادة حساب حقيقي.

### مخاطر

هذه أهم نقطة تمنع live trading: عند تعطيل dry-run قد يفشل مسار البوت قبل الوسيط، بينما الحواجز الخاصة بالمستخدم والـauto/demo ليست قوية بما يكفي. كما أن عزل consecutive-loss غير الصحيح قد يمنع مستخدمًا بسبب خسائر مستخدم آخر، في حين أن سباق daily limit قد يسمح بتجاوز الحد.

### الاختبارات

- 21 اختبارًا مركّزًا ذكرت نجاحها، كلها mocked/SQLite.
- `compileall` نجح.
- لم يُختبر broker أو MT5 الحقيقي، ولم تثبت migrations على PostgreSQL.

---

## 3.4 الاشتراكات والدفع والحدود والميزات

**الحالة: PARTIAL** — الحماية من التفعيل المزيف جيدة نسبيًا، لكن تجربة الدفع والـentitlements والتزامن غير مكتملة.

### الأدلة

- `services/subscription.py:28-193,382-468` يقرأ الخطط ويعالج expiry والlimits/features/trial.
- `services/payment.py:501-802` ينشئ الطلب، يقبل proof يدويًا، ويقصر approve على admin، بينما المسار الآلي مرفوض.
- `web/api/subscription.py:24,44-86` يوفر status/trial/proof ويعيد 404 للـwebhook.
- `bot/main.py:620-707,727-735` يربط إنشاء الطلب وفحصه وإلغاءه وانتهاء الاشتراك.
- `database/models.py:71-74,409-560` وmigrations 001/005-007/020-021 تدعم الاشتراك والدفع.
- `services/trade_executor.py:114-123,212-235,349-353` وSignalPipeline يفرضان بعض الحدود.
- `config/constants.py:94-148` يعرّف catalog منفصلًا عن القيم المزروعة في migration 006.

### ما هو موجود

- User/SubscriptionPlan/PaymentRequest وtrial وsubscription snapshot.
- حالات دفع وunique tx/replay protection.
- طلب دفع يدوي، تحقق من المبلغ/العملة/الشبكة/المستلم وملكية الطلب، وموافقة admin مع audit log.
- تطبيق daily limit وposition size وmultiple_tps وauto_trading في مسار التنفيذ.
- تجربة وخدمات status/usage/catalog.

### النواقص والأخطاء

- verifier on-chain المعلن في README غير موجود في runtime؛ webhook 404 و`process_verified_event` يرفض.
- لا توجد واجهة عملية لإدخال tx_hash/proof؛ bot يعرض التعليمات لكن لوحة الدفع لا توفر submission، وWeb لا ينشئ payment request.
- `max_symbols` و`max_connections` و`supports_api` موجودة في الخطة لكن لا توجد call sites enforcement واضحة.
- `SubscriptionService.downgrade_user` يحتاج commit موحدًا للتغييرات والsnapshot.
- `approve_payment` يستبدل expiry من الآن بدل تمديده من `max(now,current_expiry)`.
- check+increment للـdaily limit ليس atomicًا؛ سباق متزامن قد يتجاوز الحد.
- `UserRepository.create_user` يفعّل pro trial تلقائيًا رغم تصميم opt-in المحتمل.
- PaymentManager/BillingClient legacy غير موصولان، وconstants قد تختلف عن DB.

### المخاطر

الخطر ليس أساسًا تفعيلًا مزيفًا — فالموافقة محصورة بالـadmin — بل تعطل رحلة الدفع، اختلاف entitlement المعروض عن المطبق، وفقدان أيام الاشتراك أو تجاوز حدود التزامن.

### الاختبارات

- نجحت اختبارات PaymentService/subscription guard/Telegram referrals/SignalPipeline وcompileall.
- الاختبارات SQLite/mocks ولا تشمل Blockchain/PostgreSQL/Redis أو السباق الحقيقي.

---

## 3.5 إشعارات المستخدمين وقناة نتائج الصفقات

**الحالة: PARTIAL** — التصميم الدائم موجود، لكن التسليم الفعلي من web والفشل/إعادة المحاولة غير معالجين.

### الأدلة

- `services/signal_pipeline.py:258-273` يحفظ receipt ثم يستدعي notification/publication بعد executed وفي non-dry-run.
- `services/trade_executor.py:355-380` يستدعي إشعارات نتائج التنفيذ.
- `services/notification.py:98-136,162-236,330-367` ينفذ in-app/outbox/idempotency/broadcast.
- `web/runtime.py:71-90` ينشئ TradeExecutor مع bot مأخوذ من executor السابق أو `None`، و`web/app.py:39-42` يهيئ provider فقط.
- `database/models.py:352-406` وmigration 024 يوفران `TradeChannelPublication` وNotification.
- `docs/TRADINGVIEW_BROADCAST_AND_RESULTS_CHANNEL.md` يوثق retry تشغيليًا، لكن لا يوجد worker ظاهر.

### ما هو موجود

- NotificationService و`event_key` idempotency.
- durable publication بحالات `publishing/published/failed` وunique `signal_receipt_id`.
- رسائل HTML escaped ولا تتضمن Telegram ID أو بيانات حساب.
- ربط فعلي مع SignalPipeline وTradeExecutor، وليس كودًا غير مستخدم.

### النواقص والأخطاء

- `bot=None` في web runtime يجعل `publish_trade_execution` و`notify_event` يرجعان False؛ webhook الويب لا يملك قناة Telegram فعالة.
- فشل Telegram يسجل `failed` بلا worker/backoff/retry تلقائي، وidempotency يمنع إعادة pipeline لنفس receipt.
- قد تبقى `publishing` عالقة بعد crash دون lease/reclaimer.
- إشعارات التنفيذ المباشرة لا تمرر event_key دائمًا ولا تحدث `is_delivered` بصورة موحدة.
- إعدادات `notify_on_*` تحفظ ظاهريًا ولا تُفرض قبل الإرسال.
- لا توجد API ويب واضحة لقراءة Notification.

### المخاطر والاختبارات

قد تُنفذ الصفقة وتُحفظ النتيجة دون وصول إشعار المستخدم أو قناة النتائج. الاختبارات الحالية تثبت idempotency في SQLite/AsyncMock فقط، ولا تثبت executed→Telegram في عملية web منفصلة أو crash/retry.

---

## 3.6 واجهات الويب والمصادقة والأمان

**الحالة: PARTIAL** — العزل والمسارات الأساسية موجودة، لكن المخاطر الأمنية والتشغيلية تمنع اعتماد الإنتاج.

### الأدلة

- `web/app.py` يضيف routers وCORS وstartup؛ `web/deps.py` يحقق JWT/admin/user.
- `web/api/auth.py:48-127` يطبق API-key login وTelegram WebApp signed initData و`/me`.
- `web/static/js/app.js:30-49,90-119,663-668` يخزن token في localStorage ويرسله في Authorization وWebSocket query string.
- `/api/auth/login` بلا throttling ظاهر، مقابل rate limit للـwebhook فقط.
- `database/models.py` و`services/auth.py` يعرضان api_key محفوظًا/مقارنًا مباشرة، وJWT algorithm من config غير مستعمل بالكامل.
- `web/api/mt5.py` يشفر gateway key، وmigrations 012/023 تدعم إزالة كلمة مرور MT5 وربط المحرك.
- `web/static/index.html:7-9` يعتمد Tailwind CDN وGoogle Fonts، والـSPA يحتوي interpolations في `innerHTML` بلا escapeHtml شامل.

### ما هو موجود

- FastAPI routers وعزل user ownership وadmin guard.
- JWT وTelegram WebApp signature وwebhook protections.
- CORS allowlist غير wildcard.
- guest/public endpoints منفصلة عن dashboard المصادق.
- أداة `escapeHtml` موجودة وتستخدم في بعض المواضع.
- واجهة RTL وlang=ar وقائمة وتنقل وguest mode.

### النواقص والأخطاء

- XSS محتمل في status/source/direction/symbol/order/reason/timeline/MT5 errors/support subject وغيرها عند حقنها إلى HTML دون تهريب مركزي.
- token في localStorage و`/ws?token` عرضة لـXSS وتسرب access logs/proxies.
- لا يوجد throttling/lockout لـlogin، ولا logout/revocation/refresh rotation.
- API key يبدو plaintext، ولا توجد rotation/revocation مكتملة.
- `login_code` موجود في contract دون flow فعلي، و`validate_mt5_credentials` مجرد `pass`.
- JWT algorithm/issuer/audience غير موحدة.
- docs/ReDoc مفعلة علنًا، ولا تظهر Security Headers مثل CSP/HSTS.
- تعريب SPA غير مكتمل: كثير من النصوص والحالات الإنجليزية، وقيمة language تُحفظ دون i18n.
- اعتماد CDN خارجي قد يكسر الواجهة عند الفشل أو CSP.

### الاختبارات

- نجحت اختبارات auth/CORS/guest/WebSocket/e2e API و`node --check`.
- لا تثبت XSS، brute force، التسريب، HTTPS، أو deployment الحقيقي.

---

## 3.7 الإدارة والتشغيل وقاعدة البيانات والنسخ والنشر

**الحالة: BLOCKED** — توجد بنية تشغيل محلية، لكن النشر على قاعدة جديدة والجاهزية والنسخ والاستعادة غير مثبتة، وبعض العيوب قابلة للاستنتاج مباشرة.

### الأدلة

- `docker-compose.yml:37-54,56-81` يشغل bot/web بعد صحة Postgres/Redis فقط؛ لا توجد migration job.
- `database/database.py:93-100` يعرّف `create_tables` دون استدعاء runtime كبديل للمigrations.
- `alembic heads` يعيد `024_trade_channel_publications`، لكن ذلك لا يثبت تطبيق head على قاعدة فعلية.
- `web/app.py:137-149` health ثابت تقريبًا ولا يتحقق من DB/Redis/schema.
- Postgres/Redis منشوران على host افتراضيًا في Compose.
- `Dockerfile` يشغل root ولا يضع healthcheck للبوت.
- `DBPersistence` يمسك أخطاء القراءة/الكتابة ويكمل، ما قد يخفي فقدان persistence.
- `tonpo_full_backup.tar.gz` متتبع ويحتوي `.env` و`.git` وفق فحص archive، دون قراءة القيم.
- `alembic upgrade head` على SQLite المؤقت توقف عند `now()` في migration 001؛ ليس دليلًا على فشل PostgreSQL، لكنه يكشف عدم توافق SQLite المعلن مع migration.
- CI يشغل lint/mypy كـadvisory بسبب `continue-on-error: true` ولا يشغل Postgres/Redis services.

### ما هو موجود

- Bot runtime وpolling/webhook وDB manager وRedis وPTB persistence.
- سلسلة Alembic من 001 إلى 024 وMakefile migration.
- Compose volumes وrestart policy وhealthchecks أولية.
- CI للcompile/pytest/coverage.
- اختبارات repositories/runtime/persistence/Redis محلية.

### النواقص والأخطاء

- قاعدة جديدة في Compose قد تكون بلا schema قبل تشغيل bot/web.
- لا يوجد backup/restore رسمي لـPostgreSQL/Redis أو retention/RPO/RTO واختبار restore.
- health لا يميز liveness عن readiness ولا يتحقق من revision.
- نشر منافذ DB/Redis يتعارض مع runbook الذي ينصح بعدم تعريضها.
- لا يوجد deploy/release/rollback automation.
- archive source ليس backup قاعدة بيانات ويحتوي مواد حساسة تاريخية.
- web مع `ENGINE_PROVIDER=metadocker` قد يحتاج db_manager قبل تهيئة provider، وهو غير مهيأ في startup بنفس المسار.
- جودة lint/mypy ليست بوابة نشر.

### المخاطر والاختبارات

أكبر المخاطر: إقلاع خدمة على قاعدة جديدة بلا migrations، health زائف يوجّه traffic، فقدان بيانات بلا restore، وكشف أسرار archive. اختبارات Python المحلية لا تغطي Compose/PostgreSQL/Redis/MetaDocker/deploy.

---

## 4. مصفوفة الأولويات

| الأولوية | العنصر | السبب | معيار الإغلاق المقترح |
|---|---|---|---|
| **P0** | منع live trading حتى إصلاح wiring provider | مسار البوت قد لا يملك provider، وdemo/auto ليست حواجز تنفيذية | اختبار runtime يثبت أن `/trade` وchannel وweb تصل إلى provider المقصود، مع رفض صريح عند غياب binding و`TRADING_DRY_RUN=false` في staging فقط |
| **P0** | منع SSRF وتثبيت ملكية محرك MT5 | endpoint مدخل المستخدم قد يوجه الاتصال لخدمة غير موثوقة | allowlist/شبكة خاصة/TLS، تحقق ownership/account، واختبار رفض endpoint الداخلي/غير المسموح |
| **P0** | migration gate وreadiness حقيقيان | Compose الحالي قد يقلع بلا schema وhealth لا يثبت الجاهزية | job واحد `alembic upgrade head` قبل الخدمات، readiness يفحص DB/Redis/revision، smoke على Postgres فارغ وترقية |
| **P0** | تدوير الأسرار بسبب archive | `.env` متتبع داخل archive مع `.git` قد يكشف أسرارًا تاريخية | اعتبار القيم مكشوفة، تدوير BOT/JWT/ENCRYPTION/DB/API secrets، إزالة archive من التوزيع والتاريخ حيث تسمح السياسة، secret scan |
| **P0** | إصلاح عزل المخاطر والملكية | consecutive loss وclose updates قد تعبر users | `user_id` filters، اختبارات multi-user وconcurrent transaction، منع mutation خارج canonical boundary |
| **P1** | ربط التسجيل بـEngineInstance أو فصل المنتجين بوضوح | التسجيل الحالي Tonpo لا ينتج binding MetaDocker | flow موحد ينشئ/يتحقق/health-check من EngineInstance، أو توثيق فصل صريح مع UI/API binding مكتمل |
| **P1** | E2E حقيقي مع MetaDocker/MT5 demo وTradingView/Telegram | mocks لا تثبت التكامل أو reconciliation | staging موثق مع account isolation، quote/constraints/order IDs/timeout/restart/unknown result وreplay |
| **P1** | outbox worker/retry/reclaimer | failed/publishing قد تبقى بلا تسليم | worker مع backoff/lease/max attempts/metrics/alerting واختبار crash وإعادة إرسال آمنة |
| **P1** | حماية المصادقة والمتصفح | localStorage/query token وlogin بلا rate limit | HttpOnly أو تصميم access/refresh آمن، throttling/lockout، revocation، CSP/HSTS، عدم وضع token في URL |
| **P1** | فرض subscription entitlements | symbols/connections/API غير enforced | نقاط رفض واضحة واختبارات لكل plan والاتصالات والـAPI، مصدر catalog واحد |
| **P2** | إصلاح الدفع UX وتوثيقه | proof endpoint بلا واجهة، README يعلن verifier غير موجود | اختيار manual-admin أو on-chain موثوق، Bot/Web create/submit/status، تحديث docs |
| **P2** | توحيد i18n وRTL واختبارات المتصفح | العربية الحالية شكلية، وXSS جزئي | قاموس ar/en، labels للحالات، Playwright guest/auth/mobile/error/accessibility، DOM APIs بدل innerHTML غير المهرب |
| **P2** | استكمال reconciliation وclose/modify وadjust_risk | حالات UNKNOWN/P/L والمخاطرة اليدوية ناقصة | durable broker history reconciliation، تحديث P/L، حفظ risk choice واختبارات restart |
| **P3** | تنظيف legacy والجودة | كود دفع قديم وlint/mypy advisory يربكان الصيانة | حذف/عزل بعد إثبات عدم الاستخدام، إصلاح baseline، جعل quality gate تدريجيًا |
| **P3** | تحسين UX والإشعارات | notify_on_* وAPI notifications غير مكتملين | تطبيق preferences، API قراءة الإشعارات، رسائل أخطاء عربية قابلة للتصرف |

---

## 5. ما يجب عدم تغييره أو حذفه

لتجنب تراجع السلامة أثناء الإصلاح، يجب **الحفاظ على العناصر التالية وعدم حذفها أو تجاوزها**:

1. **`TRADING_DRY_RUN=true` كافتراضي** إلى أن ينجح E2E حي موثق ويُعتمد release gate.
2. **حالات `UNKNOWN` و`partial` وغياب retry التلقائي للـmutation** في طبقة التنفيذ؛ لا تُستبدل بإعادة محاولة عمياء قد تضاعف الصفقة.
3. **intent/audit/evidence قبل وبعد mutation** في TradeExecutor، و`ConnectionLog` دون أسرار.
4. **تشفير gateway/API keys وعدم تخزين كلمة مرور MT5**؛ لا تعاد كلمات المرور إلى user data أو database.
5. **عزل المستخدمين وقيود ownership** في Web API وEngineInstanceRepository، مع إصلاح القيود الناقصة لا إزالتها.
6. **HMAC وtimestamp/signal-id/idempotency وschema validation** في TradingView وTelegram pipeline.
7. **قواعد allow/block symbols، NewsProtection، emergency stop، account limits، constraints broker**؛ يجب نقلها إلى حد التنفيذ أو ضمان عدم وجود مسارات تتجاوزها، لا حذفها.
8. **قيود duplicate tx وadmin approval وaudit log** في الدفع اليدوي إلى أن يوجد verifier بديل موثوق.
9. **outbox وunique constraints وreceipt/publication states**؛ المطلوب إضافة worker/reclaimer لا إزالة durability.
10. **الـmigrations الحالية وملكية البيانات** قبل اختبار upgrade/rollback ناجح؛ لا تُستبدل عشوائيًا بـ`create_tables` في الإنتاج.
11. **CORS allowlist وadmin guards وguest/public separation**؛ لا تُفتح wildcard لتسهيل الاختبارات.
12. **الاختبارات الحالية** لا تُحذف لأنها تغطي عقودًا مهمة، لكن يجب تصنيفها بوضوح mocked/SQLite مقابل integration/E2E.
13. **الفصل بين bot وweb** لا يُفترض أنه مشاركة ذاكرة؛ إما قناة تسليم/queue مشتركة أو worker موحد، لا اعتماد على globals.

---

## 6. خطة إصلاح مرحلية محافظة

### المرحلة 0 — تجميد المخاطر (فورًا)

- أبقِ `TRADING_DRY_RUN=true`، ولا تفعّل live trading أو auto trading.
- دوّر كل الأسرار التي قد تكون في `tonpo_full_backup.tar.gz`، وافحص Git/archives دون إعادة نشر القيم.
- عطّل أو قيّد `PUT /api/mt5/engine` حتى تطبيق allowlist/private-network/TLS والتحقق من ownership.
- افصل endpoint العام عن أي provider حي، وراقب محاولات الوصول غير المسموحة.
- وثّق بوضوح أن TradingView/Telegram/Gateway/MT5 E2E غير متاحين حاليًا.

### المرحلة 1 — جعل runtime آمنًا وقابلًا للإقلاع

- أنشئ migration one-shot/lock قبل bot/web، ثم readiness يفحص DB وRedis وschema revision.
- شغّل Postgres 16 وRedis 7 في staging حقيقي، وجرّب fresh install وupgrade وrollback.
- هيئ `db_manager` قبل MetaDocker provider في web startup أو استخدم factory لا يعتمد على DB غير جاهزة.
- اربط logging/metrics بالأخطاء، واجعل DBPersistence يفشل بشكل ظاهر عند فقدان schema بدل فقدان صامت.
- اربط المنافذ بـprivate/loopback، وشغّل الحاويات non-root، وأضف healthcheck للبوت.

### المرحلة 2 — إصلاح حدود التنفيذ والعزل

- مرر provider نفسه إلى `TradingHandler` و`TradeExecutor` وclose/modify/callback paths، مع اختبار يثبت الهوية والنوع.
- اختر مسار provider معماريًا: MetaDocker أو Tonpo، أو نفّذ provisioning واضحًا لـ`EngineInstance` في التسجيل.
- طبّق `user_id` في consecutive loss وclose/update queries، وatomic claim/check للـdaily limit وpending states.
- اجعل demo/live و`ENABLE_AUTO_TRADING` وsubscription mode حواجز تنفيذية داخل canonical boundary.
- أغلق slippage/volatility عند غياب القياس، واستدعِ حماية الأخبار والسياسات داخل حد التنفيذ أو امنع الاستدعاء المباشر غير الآمن.

### المرحلة 3 — ربط MetaDocker وE2E في staging

- في بيئة غير إنتاجية، نفّذ register/bind/health/status/disable مع EngineInstance حقيقي.
- اختبر تغيير endpoint/key وإبطال cache وإغلاق الاتصالات القديمة.
- نفّذ TradingView replay وTelegram channel_post وduplicate/old timestamp وmulti-user isolation.
- اختبر MT5 demo: quote freshness، constraints، order/deal/position IDs، timeout، UNKNOWN، restart/session recovery، وreconciliation.
- لا تنقل الإعدادات إلى live قبل تقرير قبول موقع يثبت النتائج.

### المرحلة 4 — موثوقية الإشعارات والدفع

- أضف publication worker يعيد `failed` ويسترد `publishing` القديمة عبر lease/timeout وbackoff وحد محاولات.
- مرر event_key ودليل delivery موحدًا لكل إشعار، وطبّق `notify_on_*`.
- وفر قناة Telegram فعلية للـweb عبر Bot API/queue/worker مشترك، لا عبر مشاركة الذاكرة.
- اختر manual-admin أو on-chain verifier، وأكمل create/submit/status في Bot وWeb، ثم حدث README والتعليقات.
- اجعل expiry/downgrade والتفعيل transaction واحدة، واختبر السباق والتمديد من expiry الحالية.

### المرحلة 5 — أمن الويب وتجربة المستخدم

- استبدل interpolated `innerHTML` بـDOM APIs أو escape مركزي إلزامي، وأضف اختبارات XSS.
- أضف login throttling/lockout، logout/revocation/refresh rotation، وتخزين token آمنًا وعدم وضعه في query string.
- نفّذ CSP/HSTS وغيرها من security headers، وعطّل docs/ReDoc أو احمها في الإنتاج.
- أنشئ i18n ar/en حقيقيًا، تحقق من اللغة، وترجم الحالات والرسائل والبيانات الديناميكية.
- استبدل CDN runtime بأصول versioned محلية أو سياسة CSP/fallback واضحة، وأضف Playwright للـguest/login/RTL/mobile/accessibility/API outage.

### المرحلة 6 — إغلاق legacy وإطلاق مضبوط

- افصل أو احذف كود Billing/Payment legacy فقط بعد إثبات عدم وجود call sites واختبارات regression.
- وحّد مصدر plan catalog بين DB وconstants.
- أصلح lint/mypy تدريجيًا واجعله gate بعد خفض baseline.
- نفّذ backup/restore دوريًا مشفرًا مع RPO/RTO واختبار استعادة.
- أنشئ release checklist: migrations، secrets، readiness، E2E، reconciliation، rollback، monitoring، وقرار صريح لتغيير dry-run.

---

## 7. تفسير الاختبارات وحدود الثقة

- نجاح `pytest` و`compileall` يثبت غالبًا **قابلية الاستيراد وعقودًا محلية**، وليس اتصالًا بـTelegram/TradingView/Gateway/MetaDocker/MT5/Blockchain/PostgreSQL/Redis الحقيقي.
- اختبارات `MockTransport` و`AsyncMock` لا تثبت DNS/TLS/auth/network timeout أو سلوك الوسيط الحقيقي.
- اختبارات SQLite لا تثبت توافق migrations مع PostgreSQL ولا pool/locking/transaction isolation.
- static assertions للواجهة لا تثبت DOM/RTL/XSS/accessibility أو فشل CDN.
- وجود migration head لا يثبت أن قاعدة التشغيل مطبقة عليها migration.
- لا يوجد في النتائج المقدمة تشغيل order أو رسالة Telegram فعلية أو خدمة طويلة العمر أو اتصال broker حي.

---

## 8. الخلاصة والحكم النهائي

**الحكم النهائي: موجود جزئيًا، مع مسارات تنفيذ وتسجيل مكسورة، وتكاملات خارجية ونشر إنتاجي محجوبة أو غير مثبتة.**

لا ينبغي وصف الميزة كـ"مكتملة" أو تمكين التداول الحي استنادًا إلى الاختبارات الخضراء. يمكن الاحتفاظ بالبنية الحالية كنقطة انطلاق جيدة، خصوصًا SignalPipeline، durable receipts/outbox، protection، encryption، ownership، وmigration chain، لكن يجب أولًا إصلاح provider wiring، MetaDocker binding، migration/readiness، SSRF، token security، retry/reconciliation، ثم إثبات E2E حي في staging. بعد ذلك فقط يمكن تقييم انتقال محافظ من dry-run إلى MT5 demo ثم live وفق بوابة قبول مستقلة.
