/**
 * Tonpo Web Platform — client SPA
 * Connects to real /api/* endpoints. No fake data.
 */
(function () {
  'use strict';

  const API = '';
  const TITLES = {
    dashboard: 'لوحة التحكم',
    signals: 'الإشارات',
    trades: 'الصفقات',
    results: 'مركز النتائج',
    analytics: 'التحليلات الذكية',
    protection: 'مركز الحماية',
    mt5: 'اتصال MT5',
    risk: 'إدارة المخاطر',
    settings: 'الإعدادات',
    admin: 'لوحة الإدارة',
    support: 'الدعم',
    news: 'حماية الأخبار',
    subscription: 'الاشتراك والتجربة',
    account: 'الحساب / MT5',
    tradingview: 'إعداد TradingView',
    trading_mode: 'وضع التداول',
    signal: 'تفاصيل الإشارة',
    trade: 'تفاصيل الصفقة',
  };

  let token = '';
  try {
    token = sessionStorage.getItem('tonpo_token') || '';
    if (!token) {
      const legacyToken = localStorage.getItem('tonpo_token') || '';
      if (legacyToken) {
        token = legacyToken;
        sessionStorage.setItem('tonpo_token', token);
        localStorage.removeItem('tonpo_token');
      }
    }
  } catch (_) { /* Session can still be used in memory when storage is disabled. */ }
  let currentUser = null;
  let guestMode = false;
  let currentPage = 'dashboard';

  // ── HTTP ──────────────────────────────────────────────────────────────────
  async function api(path, opts = {}) {
    const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
    if (token) headers['Authorization'] = `Bearer ${token}`;
    const res = await fetch(API + path, { ...opts, headers });
    if (res.status === 401) {
      logout();
      throw new Error('Unauthorized');
    }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const safe = {400: 'The request could not be accepted.', 403: 'You are not allowed to access this resource.', 404: 'This resource is not available.', 409: 'This request conflicts with an existing decision.', 429: 'Too many requests. Please try again shortly.', 500: 'The service is temporarily unavailable.'};
      const error = new Error(safe[res.status] || 'The service could not complete this request.');
      error.status = res.status;
      throw error;
    }
    return data;
  }

  // ── Auth ──────────────────────────────────────────────────────────────────
  function showLogin() {
    document.getElementById('login-screen').classList.remove('hidden');
    document.getElementById('app').classList.add('hidden');
  }

  function showApp() {
    document.getElementById('login-screen').classList.add('hidden');
    document.getElementById('app').classList.remove('hidden');
  }

  function applyUserVisibility() {
    const admin = document.getElementById('nav-admin');
    if (admin) admin.classList.toggle('hidden', !currentUser?.is_admin);
  }

  function logout() {
    token = '';
    currentUser = null;
    guestMode = false;
    try { sessionStorage.removeItem('tonpo_token'); } catch (_) {}
    try { localStorage.removeItem('tonpo_token'); } catch (_) {}
    showLogin();
  }

  function enterGuestMode(message) {
    token = '';
    currentUser = null;
    guestMode = true;
    try { sessionStorage.removeItem('tonpo_token'); } catch (_) {}
    try { localStorage.removeItem('tonpo_token'); } catch (_) {}
    showApp();
    applyUserVisibility();
    const sidebarUser = document.getElementById('sidebar-user');
    if (sidebarUser) sidebarUser.textContent = 'وضع الاستكشاف';
    navigate('dashboard', message);
  }

  async function login(telegramId, apiKey) {
    const data = await api('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ telegram_id: Number(telegramId), api_key: apiKey }),
    });
    token = data.access_token;
    currentUser = data.user;
    guestMode = false;
    try { sessionStorage.setItem('tonpo_token', token); } catch (_) {}
    try { localStorage.removeItem('tonpo_token'); } catch (_) {}
    showApp();
    applyUserVisibility();
    document.getElementById('sidebar-user').textContent =
      currentUser.username || `ID ${currentUser.telegram_id}`;
      navigate(location.hash.slice(1) || 'dashboard');
  }

  async function loginWithTelegramWebApp(initData) {
    const data = await api('/api/auth/telegram-webapp', {
      method: 'POST',
      body: JSON.stringify({ init_data: initData }),
    });
    token = data.access_token;
    currentUser = data.user;
    guestMode = false;
    try { sessionStorage.setItem('tonpo_token', token); } catch (_) {}
    try { localStorage.removeItem('tonpo_token'); } catch (_) {}
    showApp();
    applyUserVisibility();
    document.getElementById('sidebar-user').textContent =
      currentUser.username || `ID ${currentUser.telegram_id}`;
    navigate(location.hash.slice(1) || 'dashboard');
  }

  function showTelegramWebAppStatus(message, error = false) {
    const status = document.getElementById('telegram-webapp-status');
    if (!status) return;
    status.textContent = message;
    status.classList.remove('hidden', 'text-loss', 'text-slate-400');
    status.classList.add(error ? 'text-loss' : 'text-slate-300');
  }

  // ── Navigation ────────────────────────────────────────────────────────────
  function navigate(page, guestMessage) {
    if (!TITLES[page]) page = 'dashboard';
    if (page === 'admin' && !currentUser?.is_admin) page = 'dashboard';
    currentPage = page;
    document.getElementById('page-title').textContent = TITLES[page];
    document.querySelectorAll('.nav-item').forEach((el) => {
      el.classList.toggle('active', el.dataset.page === page);
    });
    closeSidebar();
    renderPage(page, guestMessage);
  }

  function openSidebar() {
    document.getElementById('sidebar').classList.add('open');
    document.getElementById('sidebar-overlay').classList.add('open');
    document.body.classList.add('sidebar-open');
  }
  function closeSidebar() {
    document.getElementById('sidebar').classList.remove('open');
    document.getElementById('sidebar-overlay').classList.remove('open');
    document.body.classList.remove('sidebar-open');
  }

  // ── Helpers ───────────────────────────────────────────────────────────────
  function fmt(n, digits = 2) {
    if (n == null || n === undefined) return '—';
    return Number(n).toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits });
  }
  function money(n, ccy = '') {
    if (n == null) return '—';
    const s = fmt(n);
    return ccy ? `${s} ${ccy}` : s;
  }
  function escapeHtml(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  }

  function plClass(n) {
    if (n == null) return '';
    return n >= 0 ? 'text-profit' : 'text-loss';
  }
  function statusBadge(s) {
    const map = {
      executed: 'badge-green', dry_run: 'badge-yellow', partial: 'badge-blue',
      pending: 'badge-blue', confirmation_required: 'badge-yellow',
      manual_review: 'badge-yellow', failed: 'badge-red', rejected: 'badge-red',
      invalid: 'badge-red', news_blocked: 'badge-yellow', news_unavailable: 'badge-yellow', news_stale: 'badge-yellow',
      risk_blocked: 'badge-red', cancelled: 'badge-gray', received: 'badge-gray', approved: 'badge-green', execution: 'badge-blue', expired: 'badge-red', news_blocked: 'badge-yellow',
      unauthorized: 'badge-red', duplicate: 'badge-gray',
    };
    const cls = map[s] || 'badge-gray';
    return `<span class="badge ${cls}">${escapeHtml(s || '—')}</span>`;
  }
  function skeleton(rows = 4) {
    return Array.from({ length: rows }, () =>
      `<div class="skeleton mb-2" style="height:2.5rem"></div>`
    ).join('');
  }
  function empty(msg) {
    return `<div class="empty-state">
      <svg class="w-12 h-12" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1" d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A2 2 0 006.586 13H4"/></svg>
      <p>${escapeHtml(msg)}</p>
    </div>`;
  }
  function errorBox(msg) {
    return `<div class="card border-loss/30 bg-loss/5 text-loss text-sm">${escapeHtml(msg)}</div>`;
  }

  // ── Pages ─────────────────────────────────────────────────────────────────
  async function renderPage(page, guestMessage) {
    const el = document.getElementById('content');
    el.innerHTML = skeleton(6);
    try {
      if (page === 'dashboard') await renderDashboard(el, guestMessage);
      else if (guestMode) await renderGuestFeatureGate(el, page);
      else if (page === 'signals') await renderSignals(el);
      else if (page === 'trades') await renderTrades(el);
      else if (page === 'results') await renderResults(el);
      else if (page === 'analytics') await renderAnalytics(el);
      else if (page === 'protection') await renderProtection(el);
      else if (page === 'mt5' || page === 'account') await renderMT5(el);
      else if (page === 'news') await renderNews(el);
      else if (page === 'subscription') await renderSubscription(el);
      else if (page === 'tradingview') await renderTradingView(el);
      else if (page === 'trading_mode') await renderTradingMode(el);
      else if (page === 'risk') await renderRisk(el);
      else if (page === 'settings') await renderSettings(el);
      else if (page === 'support') await renderSupport(el);
      else if (page === 'admin') await renderAdmin(el);
      else if (page.startsWith('signal/')) await renderSignalDetail(el, page.split('/')[1]);
      else if (page.startsWith('trade/')) await renderTradeDetail(el, page.split('/')[1]);
    } catch (e) {
      el.innerHTML = errorBox('تعذر تحميل هذه البيانات الآن. حاول مرة أخرى لاحقًا.');
    }
  }

  async function renderGuestFeatureGate(el, page) {
    const previews = {
      signals: ['الإشارات', 'تعرّف على دورة الإشارة من الاستقبال والتحقق إلى قرار القبول أو الرفض.', 'تظهر الإشارات الفعلية بعد تسجيل الدخول فقط. هذه معاينة توضيحية وليست إشارات سوق.'],
      trades: ['الصفقات', 'راجع كيف يحفظ Tonpo قرار التنفيذ ويمرره عبر الاشتراك والمخاطر.', 'بيانات الصفقات شخصية ومحمية؛ لا توجد صفقات تجريبية معروضة هنا.'],
      results: ['مركز النتائج', 'شاهد كيف تُعرض النتائج المحفوظة فقط دون اختراع أرقام أو أرباح.', 'لا توجد نتائج عامة. ستظهر نتائج حسابك بعد تسجيل الدخول ووجود صفقات مغلقة.'],
      analytics: ['التحليلات الذكية', 'فهم الإشارات والقرارات والنتائج من بيانات الحساب المحفوظة.', 'بيانات تجريبية: لا تُعرض أرقام أو نتائج تداول حقيقية للزائر.'],
      protection: ['مركز الحماية', 'تعرّف على الإيقاف الطارئ وحدود المخاطر وحماية الأخبار قبل التنفيذ.', 'المعاينة العامة للضوابط فقط؛ القرار الفعلي يطبّقه Backend لكل حساب.'],
      mt5: ['اتصال MT5', 'تعلّم خطوات التسجيل وربط حساب MT5 عند اختيار التداول.', 'لا تطلب Tonpo كلمة مرور MT5 في الواجهة العامة. يبدأ الربط من مسار التسجيل في البوت.'],
      account: ['الحساب / MT5', 'راجع ما الذي يظهر للمستخدم المسجل: حالة الحساب والاتصال والاشتراك.', 'بيانات الحساب خاصة ولا تُعرض في وضع الاستكشاف.'],
      risk: ['إدارة المخاطر', 'افهم المخاطرة لكل صفقة والحد اليومي وحدود المراكز.', 'معاينة قراءة فقط؛ لا يمكن تغيير إعدادات الحساب دون جلسة مصادق عليها.'],
      news: ['حماية الأخبار', 'تمنع طبقة الأخبار الجديدة عندما تكون البيانات مؤثرة أو غير متاحة.', 'الحالة الخاصة بالحساب تتطلب تسجيل الدخول؛ لا توجد حالة سوق عامة معروضة.'],
      subscription: ['الاشتراك والتجربة', 'تعرّف على الخطط المعروضة في النظام وعلى تجربة 3 أيام عند الأهلية.', 'بدء التجربة أو الدفع يتطلب حسابًا. لا تبدأ التجربة بمجرد التصفح.'],
      tradingview: ['إعداد TradingView', 'تعرّف على مسار Webhook: مصادقة، تحقق، تكرار، اشتراك، مخاطر، ثم Pipeline.', 'لا تُعرض أسرار Webhook في الواجهة. الإعداد الفعلي يظل على الخادم.'],
      trading_mode: ['وضع التداول', 'افهم الفرق بين التفضيل التجريبي وضوابط الخادم.', 'لا يمكن للزائر تغيير الوضع، وTRADING_DRY_RUN يبقى حاجزًا خادميًا.'],
      settings: ['الإعدادات', 'تعرّف على الإعدادات التي يمكن للمستخدم المسجل إدارتها بأمان.', 'الإعدادات شخصية ومحمية؛ هذه الصفحة تعرض شرحًا عامًا فقط.'],
      support: ['الدعم', 'تعرّف على طريقة إرسال طلب دعم عند توفر حساب.', 'إرسال تذكرة يتطلب تسجيل الدخول؛ لا تُرسل بيانات شخصية في وضع الاستكشاف.'],
    };
    const preview = previews[page] || ['Tonpo', 'استكشف طريقة عمل المنصة وضوابطها.', 'هذه معاينة عامة للقراءة فقط.'];
    let botUsername = '';
    try { botUsername = (await api('/api/public/catalog')).bot_username || ''; } catch (_) { /* public explanation remains available */ }
    const registerAction = botUsername
      ? `<a class="inline-flex px-4 py-2 rounded-xl bg-accent-500 text-white text-sm" href="https://t.me/${encodeURIComponent(botUsername)}" target="_blank" rel="noopener">ابدأ التسجيل عند الحاجة</a>`
      : '<span class="badge badge-blue">التسجيل متاح من بوت Tonpo عند اختيار ميزة حساب</span>';
    el.innerHTML = `<div class="page-heading"><div><div class="eyebrow">TONPO · وضع الاستكشاف</div><h1 class="page-heading-title">${escapeHtml(preview[0])}</h1><p class="page-heading-sub">${escapeHtml(preview[1])}</p></div><span class="badge badge-blue">للقراءة فقط</span></div><div class="grid md:grid-cols-2 gap-4 mb-4"><div class="card"><div class="card-title">ماذا يمكنك أن تتعلم هنا؟</div><p class="text-slate-300 mt-2">${escapeHtml(preview[1])}</p><div class="flow-compact mt-4"><span>تحقق الإشارة</span><span>إدارة المخاطر</span><span>حماية الأخبار</span><span>قرار قابل للشرح</span></div></div><div class="card"><div class="card-title">حالة المعاينة</div><p class="text-slate-300 mt-2">${escapeHtml(preview[2])}</p><div class="mt-3"><span class="badge badge-blue">بيانات تجريبية — ليست بيانات تداول حقيقية</span></div></div></div><div class="card"><div class="card-title">الخطوة التالية</div><p class="text-slate-300 mt-2">استمر في تصفح الأقسام العامة. عند اختيار ميزة تتطلب حسابًا، سيظهر التسجيل في تلك اللحظة فقط.</p><div class="mt-4 flex flex-wrap gap-2">${registerAction}<a class="inline-flex px-4 py-2 rounded-xl bg-surface-700 text-slate-200 text-sm" href="#dashboard">العودة إلى الاستكشاف</a></div></div>`;
  }

  async function renderGuestDashboard(el, message) {
    let plans = [];
    let botUsername = '';
    try {
      const catalog = await api('/api/public/catalog');
      plans = Array.isArray(catalog.plans) ? catalog.plans : [];
      botUsername = catalog.bot_username || '';
    } catch (_) {
      // Static guest content remains available if the optional catalog is down.
    }
    const registerHref = botUsername ? `https://t.me/${encodeURIComponent(botUsername)}` : '';
    const planHtml = plans.length ? plans.map(plan => `
      <div class="card">
        <div class="card-title">${escapeHtml(plan.name || plan.tier || 'Plan')}</div>
        <div class="text-white font-semibold mt-1">${plan.price_monthly != null ? `${escapeHtml(plan.price_monthly)} / month` : 'السعر غير متاح'}</div>
        <div class="card-sub mt-2">${plan.max_trades_per_day != null ? `${escapeHtml(plan.max_trades_per_day)} حدّ الصفقات اليومي` : 'تفاصيل الاستخدام من النظام'}</div>
        <div class="text-xs text-slate-400 mt-2">${(plan.features || []).map(escapeHtml).join(' · ')}</div>
      </div>`).join('') : '<div class="card-sub">خطط الاشتراك غير متاحة للعرض العام حاليًا.</div>';
    el.innerHTML = `
      <div class="hero-card mb-5">
        <div><div class="eyebrow">TONPO · GUEST MODE</div>
          <h1 class="text-2xl md:text-3xl font-bold text-white mt-2">استكشف Tonpo قبل التسجيل</h1>
          <p class="text-slate-300 mt-2 max-w-2xl">تعرّف على الإشارات والحماية وإدارة المخاطر ومسار ربط MT5. لا توجد جلسة مستخدم ولا بيانات تداول خاصة في هذا الوضع.</p>
        </div><span class="badge badge-blue mt-3 md:mt-0">استكشاف عام</span>
      </div>
      ${message ? `<div class="card border-accent/30 bg-accent/5 mb-5 text-slate-300">${escapeHtml(message)}</div>` : ''}
      <div class="grid md:grid-cols-2 lg:grid-cols-3 gap-4 mb-5">
        <div class="card"><div class="card-title">كيف تعمل Tonpo؟</div><p class="card-sub mt-2">تستقبل الإشارة، تتحقق من المصدر والبنية، ثم تمررها عبر الاشتراك والمخاطر وحماية الأخبار قبل أي مسار تنفيذ.</p></div>
        <div class="card"><div class="card-title">الإشارات</div><p class="card-sub mt-2">مركز الإشارات يعرض قرارات النظام وأسباب الرفض عند توفر حساب مصرح له.</p></div>
        <div class="card"><div class="card-title">الحماية وإدارة المخاطر</div><p class="card-sub mt-2">قواعد المخاطر وحماية الأخبار وDRY RUN تُفرض في Backend ولا يمكن تجاوزها من الواجهة.</p></div>
        <div class="card"><div class="card-title">ربط MT5</div><p class="card-sub mt-2">عند اختيار ميزة الحساب، استخدم مسار التسجيل الموجود في البوت عبر الأمر <span class="mono">/register</span>.</p></div>
        <div class="card"><div class="card-title">المعاينة</div><p class="card-sub mt-2">المحتوى العام يشرح سير العمل فقط؛ لا تُعرض بيانات تجريبية على أنها نتائج تداول حقيقية.</p></div>
        <div class="card"><div class="card-title">الصلاحيات</div><p class="card-sub mt-2">الصفقات والنتائج والحساب والإعدادات والدعم الخاص تبقى محمية وتتطلب جلسة مستخدم حقيقية.</p></div>
      </div>
      <div class="card mb-5"><div class="card-title">خطط الاشتراك المعروفة في النظام</div><div class="grid md:grid-cols-2 lg:grid-cols-3 gap-3 mt-4">${planHtml}</div></div>
      <div class="card flex flex-wrap items-center justify-between gap-3">
        <div><div class="text-white font-semibold">هل تريد استخدام ميزة حساب؟</div><div class="card-sub mt-1">ابدأ التسجيل من بوت Telegram عند الحاجة؛ لا تحتاج API Key لفتح Mini App.</div></div>
        ${registerHref ? `<a class="inline-flex px-4 py-2 rounded-xl bg-accent-500 text-white text-sm" href="${registerHref}" target="_blank" rel="noopener">فتح بوت Tonpo</a>` : '<span class="badge badge-yellow">استخدم /register في بوت Tonpo</span>'}
      </div>`;
  }

  async function renderDashboard(el, guestMessage) {
    const [data, news] = guestMode
      ? [await api('/api/public/overview'), {status: 'unavailable', reason: 'تظهر حماية الأخبار الخاصة بعد تسجيل الدخول.'}]
      : await Promise.all([api('/api/dashboard'), api('/api/news/status')]);
    const a = data.account || {};
    const activity = data.activity || { has_data: false };
    updateConnBadge(a.connected, data.dry_run);
    const sub = data.subscription || {};
    const statuses = data.statuses || {};
    const cards = [
      { title: 'حالة DRY RUN', value: data.dry_run ? 'مفعّل' : 'محظور', sub: 'لا أوامر حقيقية', cls: 'text-amber-300' },
      { title: 'MT5', value: a.connected ? 'متصل' : 'غير متصل', sub: a.connected ? 'اتصال مؤكد' : 'اربط الحساب للبدء', cls: a.connected ? 'text-profit' : 'text-loss' },
      { title: 'محرك التداول', value: statuses.engine === 'dry_run' ? 'جاهز للفحص' : 'محظور', sub: 'يمر عبر الـPipeline الحالي' },
      { title: 'الاشتراك', value: sub.status || 'غير متاح', sub: sub.trial?.active ? `Trial: ${sub.trial.remaining_days} يوم متبقٍ` : (sub.available ? 'الميزة متاحة' : 'الميزة غير متاحة') },
    ];
    let html = `${guestMessage ? `<div class="card border-accent/30 bg-accent/5 mb-4 text-slate-300">${escapeHtml(guestMessage)}</div>` : ''}<div class="hero-card mb-5"><div><div class="eyebrow">TONPO</div><h1 class="text-2xl md:text-3xl font-bold text-white mt-2">Automated Trading Protection &amp; Execution</h1><p class="text-slate-400 mt-2 max-w-2xl">Tonpo لا يأخذ الإشارات بشكل أعمى: يتحقق من الإشارة والمخاطر والأخبار والأهلية قبل المرور إلى التنفيذ.</p></div><span class="badge badge-yellow mt-3 md:mt-0">DRY RUN — لا أوامر حقيقية</span></div>`;
    const tvConfigured = Boolean((data.onboarding?.steps || []).find(step => step.key === 'signal_source')?.complete);
    const newsState = news.status === 'inactive' ? 'SAFE' : news.status === 'active' ? 'PROTECTED' : news.status === 'stale' ? 'STALE DATA' : news.status === 'unavailable' ? 'DATA UNAVAILABLE' : 'CONFIGURATION REQUIRED';
    const engineState = data.dry_run && sub.available ? (a.connected ? 'READY' : 'NOT READY') : 'NOT READY';
    html += `<div class="premium-status-grid mb-5">${stateBadge('Trading Engine', engineState)}${stateBadge('TradingView', tvConfigured ? 'CONFIGURED' : 'NOT CONFIGURED')}${stateBadge('News Protection', newsState)}${stateBadge('MT5 Account', a.connected ? 'CONNECTED' : 'NOT CONNECTED')}${stateBadge('Subscription', trialActiveLabel(sub))}${stateBadge('DRY RUN', 'ON')}</div>`;
    html += `<div class="card mb-5 value-proposition"><div class="card-title">Why Tonpo?</div><p class="text-slate-200">Tonpo validates signals, checks risk, protects against major news, and explains every decision before execution.</p><div class="value-grid mt-4"><span>Signal Intelligence</span><span>Risk Protection</span><span>News Protection</span><span>Explainable Execution</span><span>User Isolation</span><span>Subscription-controlled automation</span></div></div>`;
    html += `<div class="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-5">`;
    for (const c of cards) html += `<div class="card"><div class="card-title">${escapeHtml(c.title)}</div><div class="card-value text-base ${c.cls || ''}">${escapeHtml(c.value)}</div><div class="card-sub">${escapeHtml(c.sub || '')}</div></div>`;
    html += `</div>`;
    const trial = sub.trial || {};
    html += `<div class="grid lg:grid-cols-3 gap-4 mb-4"><div class="card"><div class="card-title">Account / Subscription</div><div class="text-lg font-semibold text-white">${escapeHtml(sub.plan || data.user?.subscription_tier || 'free')}</div><div class="mt-2">${trial.active ? `<span class="badge badge-blue">Trial active</span><div class="card-sub mt-2">متبقٍ ${escapeHtml(trial.remaining_days)} يوم — حتى ${trial.ends_at ? new Date(trial.ends_at).toLocaleDateString('ar') : '—'}</div>` : `<span class="badge ${sub.available ? 'badge-green' : 'badge-red'}">${sub.available ? 'الميزة متاحة' : 'الميزة غير متاحة'}</span>${sub.available ? '' : '<div class="card-sub mt-2">الترقية مطلوبة للمتابعة.</div>'}`}</div></div><div class="card"><div class="card-title">Trading Status</div><div class="status-line"><span class="status-dot ${a.connected ? 'ok' : 'bad'}"></span><span>MT5: ${a.connected ? 'متصل' : 'غير متصل'}</span></div><div class="status-line"><span class="status-dot ok"></span><span>Engine: ${statuses.engine === 'dry_run' ? 'DRY RUN' : 'محظور'}</span></div><div class="status-line"><span class="status-dot ${news.status === 'inactive' ? 'ok' : 'warn'}"></span><span>News: ${escapeHtml(news.status || 'غير متاح')}</span></div></div><div class="card"><div class="card-title">حماية الأخبار</div><div class="text-base font-semibold ${news.status === 'inactive' ? 'text-profit' : 'text-amber-300'}">${news.status === 'inactive' ? 'SAFE' : news.status === 'active' ? 'PROTECTED' : news.status === 'stale' || news.status === 'unavailable' ? 'STALE / UNAVAILABLE' : 'RESUMING'}</div><div class="card-sub mt-2">${escapeHtml(news.reason || 'لا توجد بيانات مؤكدة.')}</div></div></div>`;
    if (activity.has_data) {
      html += `<div class="card mb-4"><div class="flex justify-between items-center mb-3"><div><div class="card-title">Today's Activity</div><div class="text-xs text-slate-500">بيانات اليوم الفعلية فقط</div></div></div><div class="grid grid-cols-2 md:grid-cols-5 gap-3"><div><div class="card-title">Signals received</div><div class="card-value text-base">${escapeHtml(activity.signals_received ?? 0)}</div></div><div><div class="card-title">Accepted</div><div class="card-value text-base text-profit">${escapeHtml(activity.signals_accepted ?? 0)}</div></div><div><div class="card-title">Rejected</div><div class="card-value text-base text-loss">${escapeHtml(activity.signals_rejected ?? 0)}</div></div><div><div class="card-title">Trades executed</div><div class="card-value text-base">${escapeHtml(activity.trades_executed ?? 0)}</div></div><div><div class="card-title">Active</div><div class="card-value text-base">${escapeHtml(activity.trades_active ?? 0)}</div></div></div></div>`;
    } else html += `<div class="card mb-4">${empty('لا توجد نشاطات اليوم — ستظهر الإشارات والصفقات الفعلية هنا.')}</div>`;
    if (data.onboarding && !data.onboarding.ready) html += `<div class="card mb-4"><div class="flex justify-between items-center mb-3"><div><div class="card-title">Onboarding</div><div class="text-white font-semibold">أكمل المتطلبات الحقيقية قبل التداول</div></div><span class="badge badge-yellow">غير جاهز بعد</span></div><div class="grid sm:grid-cols-2 lg:grid-cols-3 gap-2">${data.onboarding.steps.map(step => `<div class="onboarding-step ${step.complete ? 'complete' : ''}"><span>${step.complete ? '✓' : '○'}</span>${escapeHtml(step.label)}</div>`).join('')}</div></div>`;
    html += `<div class="grid lg:grid-cols-2 gap-4"><div class="card !p-0 overflow-hidden"><div class="px-4 py-3 border-b border-surface-600 flex justify-between items-center"><span class="text-sm font-semibold text-white">آخر الإشارات</span><a href="#signals" class="text-xs text-accent-glow">عرض الكل</a></div>${data.recent_signals?.length ? `<div class="table-wrap border-0 rounded-none"><table class="data"><thead><tr><th>المصدر</th><th>الحالة</th><th>الوقت</th></tr></thead><tbody>${data.recent_signals.slice(0,8).map(s => `<tr><td class="mono text-xs">${escapeHtml(s.source || '—')}</td><td>${statusBadge(s.status)}</td><td class="text-slate-500 text-xs">${s.created_at ? new Date(s.created_at).toLocaleString('ar') : '—'}</td></tr>`).join('')}</tbody></table></div>` : empty('No signals yet — ستظهر أول إشارة TradingView هنا.')}</div><div class="card !p-0 overflow-hidden"><div class="px-4 py-3 border-b border-surface-600 flex justify-between items-center"><span class="text-sm font-semibold text-white">آخر الصفقات</span><a href="#trades" class="text-xs text-accent-glow">عرض الكل</a></div>${data.recent_trades?.length ? `<div class="table-wrap border-0 rounded-none"><table class="data"><thead><tr><th>الرمز</th><th>النوع</th><th>الحجم</th><th>الحالة</th></tr></thead><tbody>${data.recent_trades.slice(0,8).map(t => `<tr><td class="mono font-medium text-white">${escapeHtml(t.symbol || '—')}</td><td>${escapeHtml(t.order_type || '—')}</td><td class="mono">${escapeHtml(t.position_size ?? '—')}</td><td>${statusBadge(t.status)}</td></tr>`).join('')}</tbody></table></div>` : empty('No trades yet — ستظهر الصفقات الفعلية بعد المرور بالضوابط.')}</div></div>`;
    el.innerHTML = html;
  }

  async function renderSignals(el) {
    const data = await api('/api/signals?limit=50');
    if (!data.items || !data.items.length) {
      el.innerHTML = empty('لا توجد إشارات بعد — أرسل إشارة من TradingView');
      return;
    }
    let html = `<div class="card !p-0 overflow-hidden">
      <div class="px-4 py-3 border-b border-surface-600">
        <span class="text-sm font-semibold text-white">الإشارات (${escapeHtml(data.total)})</span>
      </div>
      <div class="table-wrap border-0 rounded-none"><table class="data"><thead><tr>
        <th>الرمز</th><th>الاتجاه</th><th>الدخول</th><th>SL</th><th>TP</th><th>المصدر</th><th>الحالة</th><th>السبب</th><th>الوقت</th>
      </tr></thead><tbody>`;
    for (const s of data.items) {
      html += `<tr class="cursor-pointer hover:bg-surface-700/40" data-signal-id="${escapeHtml(s.id)}">
        <td class="mono font-medium text-white">${escapeHtml(s.symbol || '—')}</td>
        <td>${s.direction ? `<span class="badge ${s.direction.includes('BUY') || s.direction.includes('Buy') ? 'badge-green' : 'badge-red'}">${escapeHtml(s.direction)}</span>` : '—'}</td>
        <td class="mono">${escapeHtml(s.entry || '—')}</td>
        <td class="mono">${escapeHtml(s.stop_loss || '—')}</td>
        <td class="mono text-xs">${escapeHtml((s.take_profits || []).join(', ') || '—')}</td>
        <td class="text-xs">${escapeHtml(s.source || '—')}</td>
        <td>${statusBadge(s.status)}</td>
        <td class="text-xs text-slate-400">${escapeHtml(s.rejection_reason || s.news_status || '—')}</td>
        <td class="text-slate-500 text-xs whitespace-nowrap">${s.created_at ? new Date(s.created_at).toLocaleString('ar') : '—'}</td>
      </tr>`;
    }
    html += `</tbody></table></div></div>`;
    el.innerHTML = html;
    el.querySelectorAll('[data-signal-id]').forEach(row => {
      row.addEventListener('click', () => {
        const id = row.dataset.signalId || '';
        if (/^\d+$/.test(id)) location.hash = `signal/${id}`;
      });
    });

  }

  async function renderTrades(el) {
    const data = await api('/api/trades?limit=50');
    if (!data.items || !data.items.length) {
      el.innerHTML = empty('لا توجد صفقات بعد');
      return;
    }
    let html = `<div class="card !p-0 overflow-hidden">
      <div class="px-4 py-3 border-b border-surface-600">
        <span class="text-sm font-semibold text-white">الصفقات (${escapeHtml(data.total)})</span>
      </div>
      <div class="table-wrap border-0 rounded-none"><table class="data"><thead><tr>
        <th>الرمز</th><th>النوع</th><th>الدخول</th><th>الحجم</th><th>المخاطرة</th><th>الحالة</th><th>الوقت</th>
      </tr></thead><tbody>`;
    for (const t of data.items) {
      html += `<tr class="cursor-pointer hover:bg-surface-700/40" data-trade-id="${escapeHtml(t.id)}">
        <td class="mono font-medium text-white">${escapeHtml(t.symbol || '—')}</td>
        <td>${escapeHtml(t.order_type || '—')}</td>
        <td class="mono">${escapeHtml(t.entry_price ?? '—')}</td>
        <td class="mono">${escapeHtml(t.position_size ?? '—')}</td>
        <td class="mono">${escapeHtml(t.risk_percentage != null ? t.risk_percentage + '%' : '—')}</td>
        <td>${statusBadge(t.status)}</td>
        <td class="text-slate-500 text-xs whitespace-nowrap">${t.created_at ? new Date(t.created_at).toLocaleString('ar') : '—'}</td>
      </tr>`;
    }
    html += `</tbody></table></div></div>`;
    el.innerHTML = html;
    el.querySelectorAll('[data-trade-id]').forEach(row => {
      row.addEventListener('click', () => {
        const id = row.dataset.tradeId || '';
        if (/^\d+$/.test(id)) location.hash = `trade/${id}`;
      });
    });

  }

  async function renderResults(el) {
    const period = new URLSearchParams(location.hash.split('?')[1] || '').get('period') || '30d';
    const data = await api('/api/results?period=' + encodeURIComponent(period));
    const filters = ['today','7d','30d','all'];
    let html = `<div class="flex flex-wrap gap-2 mb-4">${filters.map(p => `<a href="#results?period=${p}" class="px-3 py-2 rounded-xl text-xs ${p === period ? 'bg-accent-500 text-white' : 'bg-surface-700 text-slate-300'}">${p === 'today' ? 'اليوم' : p === '7d' ? '7 أيام' : p === '30d' ? '30 يومًا' : 'كل الوقت'}</a>`).join('')}</div>`;
    if (!data.has_data && !data.has_signals) { el.innerHTML = html + `<div class="card">${empty('No data for selected period — لا توجد إشارات أو صفقات في الفترة المحددة.')}</div>`; return; }
    const m = data.metrics || {};
    const cards = [['الصفقات المغلقة', m.total_closed_trades], ['الرابحة', m.winning_trades], ['الخاسرة', m.losing_trades], ['نسبة الفوز', m.win_rate == null ? null : m.win_rate + '%'], ['إجمالي P/L', m.total_pnl]];
    html += `<div class="grid grid-cols-2 lg:grid-cols-5 gap-3 mb-4">${cards.map(([title,value]) => `<div class="card"><div class="card-title">${escapeHtml(title)}</div><div class="card-value text-base">${value == null ? '—' : title.includes('P/L') ? money(value) : escapeHtml(value)}</div></div>`).join('')}</div>`;
    const signals = data.signals || [];
    html += `<div class="card !p-0 overflow-hidden mb-4"><div class="px-4 py-3 border-b border-surface-600"><span class="text-sm font-semibold text-white">Signal decisions</span></div>${signals.length ? `<div class="table-wrap border-0 rounded-none"><table class="data"><thead><tr><th>الوقت</th><th>المصدر</th><th>الحالة</th><th>السبب</th><th>News</th><th>Execution</th></tr></thead><tbody>${signals.map(s => `<tr><td class="text-xs whitespace-nowrap">${s.created_at ? new Date(s.created_at).toLocaleString('ar') : '—'}</td><td>${escapeHtml(s.source || '—')}</td><td>${statusBadge(s.status)}</td><td class="text-xs">${escapeHtml(s.rejection_reason || (s.status === 'rejected' ? 'Unknown execution state' : '—'))}</td><td>${escapeHtml(s.news_status || '—')}</td><td>${s.trade_id ? 'trade record' : '—'}</td></tr>`).join('')}</tbody></table></div>` : empty('No signals yet')}</div>`;
    const trades = data.trades || [];
    html += `<div class="card !p-0 overflow-hidden"><div class="px-4 py-3 border-b border-surface-600 text-sm font-semibold text-white">Closed trades</div>${trades.length ? `<div class="table-wrap border-0 rounded-none"><table class="data"><thead><tr><th>الوقت</th><th>الرمز</th><th>الاتجاه</th><th>P/L</th><th>الحالة</th></tr></thead><tbody>${trades.map(t => `<tr><td class="text-xs">${t.closed_at ? new Date(t.closed_at).toLocaleString('ar') : '—'}</td><td class="mono">${escapeHtml(t.symbol || '—')}</td><td>${escapeHtml(t.order_type || '—')}</td><td class="mono ${plClass(t.profit_loss)}">${money(t.profit_loss)}</td><td>${statusBadge(t.status)}</td></tr>`).join('')}</tbody></table></div>` : empty('No trades yet — Approved signals will appear here when execution is enabled.')}</div>`;
    el.innerHTML = html;
  }

  async function renderAnalytics(el) {
    const data = await api('/api/analytics?period=30d');
    if (!data.has_data) { el.innerHTML = `<div class="page-heading"><div><div class="eyebrow">REAL DATA ONLY</div><h1 class="page-heading-title">Smart Analytics</h1></div></div><div class="card">${empty(data.message || 'No analytics data')}</div>`; return; }
    const m = data.metrics || {};
    const cards = [['Signals', m.total_signals], ['Accepted', m.accepted_signals], ['Rejected', m.rejected_signals], ['Executed', m.executed_trades], ['Win rate', m.win_rate == null ? null : `${m.win_rate}%`], ['Total P/L', m.total_pnl]];
    el.innerHTML = `<div class="page-heading"><div><div class="eyebrow">PERSISTED DECISIONS</div><h1 class="page-heading-title">Smart Analytics</h1><p class="page-heading-sub">Calculated from your authorized persisted signals and trades only.</p></div></div><div class="grid grid-cols-2 lg:grid-cols-6 gap-3">${cards.map(([k,v]) => `<div class="card"><div class="card-title">${escapeHtml(k)}</div><div class="card-value text-base">${v == null ? 'Unavailable' : escapeHtml(v)}</div></div>`).join('')}</div><div class="grid md:grid-cols-2 gap-4 mt-4"><div class="card"><div class="card-title">Rejection categories</div>${Object.entries(data.rejection_categories || {}).map(([k,v]) => `<div class="flex justify-between py-2 border-b border-surface-600"><span>${escapeHtml(k)}</span><strong>${escapeHtml(v)}</strong></div>`).join('') || '<div class="empty-inline">No rejected signals</div>'}</div><div class="card"><div class="card-title">Daily P/L</div>${Object.entries(data.daily_pnl || {}).map(([k,v]) => `<div class="flex justify-between py-2 border-b border-surface-600"><span>${escapeHtml(k)}</span><strong class="${plClass(v)}">${money(v)}</strong></div>`).join('') || '<div class="empty-inline">No closed results</div>'}</div></div>`;
  }

  async function renderProtection(el) {
    const data = await api('/api/protection');
    const kill = data.kill_switch?.active ? 'ACTIVE' : 'INACTIVE';
    const news = data.news?.status || 'unavailable';
    el.innerHTML = `<div class="page-heading"><div><div class="eyebrow">DETERMINISTIC SAFETY</div><h1 class="page-heading-title">Protection Center</h1><p class="page-heading-sub">These controls are enforced by the backend; the UI cannot authorize execution.</p></div>${stateBadge('Kill switch', kill)}</div><div class="grid md:grid-cols-2 lg:grid-cols-3 gap-4"><div class="card"><div class="card-title">Kill switch</div><div class="text-xl font-bold">${kill}</div><p class="card-sub">${kill === 'ACTIVE' ? 'New execution is blocked.' : 'No active emergency stop reported.'}</p></div><div class="card"><div class="card-title">News Protection</div><div class="text-xl font-bold">${escapeHtml(news.toUpperCase())}</div><p class="card-sub">${escapeHtml(data.news?.reason || 'Protection state unavailable')}</p></div><div class="card"><div class="card-title">Execution mode</div><div class="text-xl font-bold text-amber-300">DRY RUN</div><p class="card-sub">No real broker orders are allowed.</p></div></div>`;
  }

  function trialActiveLabel(sub) { return sub?.trial?.active ? 'TRIAL' : (sub?.status === 'ACTIVE' ? 'ACTIVE' : (sub?.status === 'EXPIRED' ? 'EXPIRED' : 'NOT ACTIVE')); }

  function stateTone(state) {
    if (['READY', 'SAFE', 'CONNECTED', 'ACTIVE', 'CONFIGURED'].includes(state)) return 'good';
    if (['PROTECTED', 'TRIAL', 'CONFIGURATION REQUIRED', 'NOT CONFIGURED', 'DATA UNAVAILABLE', 'STALE DATA'].includes(state)) return 'warn';
    return 'bad';
  }

  function stateBadge(label, state) {
    const tone = stateTone(state);
    return `<div class="premium-status ${tone}"><div class="status-label">${escapeHtml(label)}</div><div class="status-value">${escapeHtml(state)}</div></div>`;
  }

  async function renderNews(el) {
    const data = await api('/api/news/status');
    const state = data.status === 'inactive' ? 'SAFE' : data.status === 'active' ? 'PROTECTED' : data.status === 'stale' ? 'STALE DATA' : data.status === 'unavailable' ? 'DATA UNAVAILABLE' : 'CONFIGURATION REQUIRED';
    const explanation = state === 'SAFE' ? 'No high-impact events are currently affecting your symbols.' : state === 'PROTECTED' ? 'Trading is temporarily paused because of a high-impact economic event.' : 'Market-event data is unavailable or stale. New trades remain blocked until fresh data is available.';
    el.innerHTML = `<div class="page-heading"><div><div class="eyebrow">SAFETY LAYER</div><h1 class="page-heading-title">News Protection</h1><p class="page-heading-sub">The backend decides whether a new signal may proceed.</p></div>${stateBadge('Current state', state)}</div><div class="grid md:grid-cols-2 gap-4"><div class="card"><div class="card-title">Protection status</div><div class="text-xl font-bold ${state === 'SAFE' ? 'text-profit' : 'text-amber-300'}">${state}</div><p class="card-sub mt-2">${explanation}</p></div><div class="card"><div class="card-title">Provider evidence</div><div class="text-white">${escapeHtml(data.provider || 'Unavailable')}</div><div class="card-sub mt-2">${data.last_update ? `Last update: ${new Date(data.last_update).toLocaleString()}` : 'Freshness unavailable'}</div><div class="mt-3">${data.blocks_new_trades ? '<span class="badge badge-yellow">New trades blocked</span>' : '<span class="badge badge-green">No protection block reported</span>'}</div></div></div>`;
  }

  async function renderSubscription(el) {
    const data = await api('/api/dashboard');
    const sub = data.subscription || {};
    const trial = sub.trial || {};
    const state = trial.active ? 'TRIAL' : (sub.status || 'UNAVAILABLE');
    const tone = sub.available ? 'good' : 'bad';
    const features = Object.entries(sub.features || {}).filter(([, value]) => value != null);
    const canStartTrial = trial.status === 'NOT_STARTED';
    el.innerHTML = `<div class="page-heading"><div><div class="eyebrow">ACCESS CONTROL</div><h1 class="page-heading-title">Subscription & Trial</h1><p class="page-heading-sub">Access is enforced by the backend for every signal.</p></div><div class="premium-status ${tone}"><div class="status-label">Status</div><div class="status-value">${escapeHtml(state)}</div></div></div><div class="grid md:grid-cols-2 lg:grid-cols-3 gap-4"><div class="card"><div class="card-title">Current plan</div><div class="card-value text-xl">${escapeHtml(sub.plan || 'Unavailable')}</div><div class="card-sub">${sub.expiry ? `Until ${new Date(sub.expiry).toLocaleDateString()}` : 'Expiry unavailable'}</div></div><div class="card"><div class="card-title">Trial</div><div class="text-white font-semibold">${trial.active ? 'Active' : trial.ends_at ? 'Expired' : 'Not started'}</div><div class="card-sub">${trial.active ? `${escapeHtml(trial.remaining_days)} days remaining` : trial.ends_at ? 'Trial cannot be restarted.' : 'One server-authorized trial is available when eligible.'}</div>${canStartTrial ? '<button id="start-trial" class="mt-3 px-3 py-2 rounded-xl bg-accent-500 text-white text-sm">Start 3-day trial</button>' : ''}</div><div class="card"><div class="card-title">Usage</div><div class="text-white font-semibold">${escapeHtml(sub.trades_today ?? '—')} / ${escapeHtml(sub.trade_limit ?? '—')}</div><div class="card-sub">Trades today / configured limit</div></div></div><div class="card mt-4"><div class="card-title">Feature access</div>${features.length ? `<div class="feature-list">${features.map(([key, value]) => `<div><span>${escapeHtml(key)}</span><strong>${escapeHtml(value)}</strong></div>`).join('')}</div>` : '<div class="empty-inline">Feature entitlements unavailable.</div>'}</div>`;
    const trialButton = document.getElementById('start-trial');
    if (trialButton) trialButton.onclick = async () => {
      trialButton.disabled = true;
      trialButton.textContent = 'Starting…';
      try { await api('/api/subscription/trial', {method: 'POST'}); await renderSubscription(el); }
      catch (error) { trialButton.disabled = false; trialButton.textContent = 'Start 3-day trial'; el.insertAdjacentHTML('beforeend', errorBox(error.message || 'Trial is unavailable.')); }
    };
  }

  async function renderTradingMode(el) {
    const data = await api('/api/trading-mode');
    el.innerHTML = `<div class="page-heading"><div><div class="eyebrow">EXECUTION POLICY</div><h1 class="page-heading-title">Trading Mode</h1><p class="page-heading-sub">This preference never overrides server safety controls.</p></div><span class="badge badge-yellow">${escapeHtml(data.badge || 'DRY RUN')}</span></div><div class="card max-w-2xl space-y-4"><div class="text-slate-300">Current mode: <strong class="text-white">${escapeHtml(data.mode)}</strong></div><div class="card-sub">${escapeHtml(data.note || '')}</div><div class="flex flex-wrap gap-2"><button id="mode-demo" class="px-4 py-2 rounded-xl bg-surface-700 text-white">Use DEMO</button><button id="mode-live" class="px-4 py-2 rounded-xl bg-warn/20 text-warn">Select LIVE preference</button></div><div id="mode-message" class="text-sm text-slate-400"></div></div>`;
    const update = async (mode, confirm_live = false) => {
      const message = document.getElementById('mode-message');
      try { const result = await api('/api/trading-mode', {method: 'PATCH', body: JSON.stringify({mode, confirm_live})}); message.textContent = `${result.badge}: ${result.note}`; }
      catch (error) { message.textContent = error.message || 'Mode change rejected.'; }
    };
    document.getElementById('mode-demo').onclick = () => update('demo');
    document.getElementById('mode-live').onclick = () => {
      if (window.confirm('LIVE is only a preference and cannot bypass server DRY RUN. Continue?')) update('live', true);
    };
  }

  async function renderTradingView(el) {
    const data = await api('/api/dashboard');
    const step = (data.onboarding?.steps || []).find(item => item.key === 'signal_source');
    const configured = Boolean(step?.complete);
    const state = configured ? 'CONFIGURED' : 'NOT CONFIGURED';
    el.innerHTML = `<div class="page-heading"><div><div class="eyebrow">SIGNAL INTAKE</div><h1 class="page-heading-title">TradingView</h1><p class="page-heading-sub">Authenticated webhook intake only. Execution still passes through the shared safeguards.</p></div><div class="premium-status ${configured ? 'good' : 'warn'}"><div class="status-label">Webhook readiness</div><div class="status-value">${escapeHtml(state)}</div></div></div><div class="grid md:grid-cols-2 gap-4"><div class="card"><div class="card-title">Configuration</div><div class="text-xl font-bold">${state}</div><p class="card-sub mt-2">${configured ? 'Authentication configuration is present. The secret is never displayed.' : 'TradingView is not configured yet.'}</p></div><div class="card"><div class="card-title">Processing path</div><div class="flow-compact"><span>Authenticate</span><span>Validate</span><span>Replay / duplicate</span><span>Subscription</span><span>Risk + News</span><span>SignalPipeline</span><span>TradeExecutor</span></div></div></div><div class="card mt-4"><div class="card-title">Next step</div><p class="text-slate-300">${configured ? 'Send a valid signal and review its decision in Signal Center.' : 'Configure the TradingView webhook through the trusted server configuration. Do not place secrets in this page.'}</p><a href="#signals" class="inline-flex mt-4 px-4 py-2 rounded-xl bg-accent-500 text-white text-sm">Open Signal Center</a></div>`;
  }

  async function renderMT5(el) {
    const data = await api('/api/mt5/status');
    updateConnBadge(data.connected, data.dry_run);
    let html = `<div class="grid md:grid-cols-2 gap-4">`;
    html += `<div class="card">
      <div class="card-title">حالة الاتصال</div>
      <div class="flex items-center gap-2 mt-2">
        <span class="w-2.5 h-2.5 rounded-full ${data.connected ? 'bg-profit' : 'bg-loss'}"></span>
        <span class="text-lg font-semibold ${data.connected ? 'text-profit' : 'text-loss'}">${data.connected ? 'متصل' : 'غير متصل'}</span>
      </div>
      <div class="card-sub mt-2">${escapeHtml(data.message || '')}</div>
      ${data.dry_run ? '<div class="mt-3"><span class="badge badge-yellow">DRY RUN — لا أوامر حقيقية</span></div>' : ''}
    </div>`;
    html += `<div class="card space-y-3">
      <div class="flex justify-between"><span class="text-slate-400 text-sm">الحساب</span><span class="mono text-white">${escapeHtml(data.account || '—')}</span></div>
      <div class="flex justify-between"><span class="text-slate-400 text-sm">الوسيط</span><span class="mono text-white">${escapeHtml(data.broker || '—')}</span></div>
      <div class="flex justify-between"><span class="text-slate-400 text-sm">الرصيد</span><span class="mono text-white">${money(data.balance)}</span></div>
      <div class="flex justify-between"><span class="text-slate-400 text-sm">الأسهم</span><span class="mono text-white">${money(data.equity)}</span></div>
      <div class="flex justify-between"><span class="text-slate-400 text-sm">الهامش</span><span class="mono text-white">${money(data.margin)}</span></div>
      <div class="flex justify-between"><span class="text-slate-400 text-sm">آخر نبضة</span><span class="mono text-xs text-slate-400">${data.last_heartbeat ? new Date(data.last_heartbeat).toLocaleString('ar') : '—'}</span></div>
    </div></div>`;
    if (data.errors && data.errors.length) {
      html += `<div class="card border-loss/30 bg-loss/5 mt-4">
        <div class="card-title text-loss">أخطاء الاتصال</div>
        <ul class="text-sm text-loss/90 space-y-1 mt-2">${data.errors.map(e => `<li>• ${escapeHtml(e)}</li>`).join('')}</ul>
      </div>`;
    }
    el.innerHTML = html;
  }

  async function renderRisk(el) {
    const data = await api('/api/risk');
    el.innerHTML = `<div class="grid md:grid-cols-2 gap-4">
      <div class="card space-y-4">
        <div class="flex justify-between items-center">
          <span class="text-slate-400 text-sm">المخاطرة لكل صفقة</span>
          <span class="mono text-xl font-bold text-white">${(data.risk_per_trade * 100).toFixed(2)}%</span>
        </div>
        <div class="flex justify-between"><span class="text-slate-400 text-sm">أقصى خسارة يومية</span><span class="mono">${escapeHtml(data.max_daily_loss ?? '—')}</span></div>
        <div class="flex justify-between"><span class="text-slate-400 text-sm">أقصى صفقات مفتوحة</span><span class="mono">${escapeHtml(data.max_open_trades ?? '—')}</span></div>
        <div class="flex justify-between"><span class="text-slate-400 text-sm">أقصى سبريد</span><span class="mono">${escapeHtml(data.max_spread ?? '—')}</span></div>
        <div class="pt-2">${data.dry_run ? '<span class="badge badge-yellow">DRY RUN نشط</span>' : '<span class="badge badge-green">Live</span>'}</div>
      </div>
      <div class="card">
        <div class="card-title">الرموز المسموحة</div>
        <div class="text-sm text-slate-300 mt-2">${(data.allowed_symbols && data.allowed_symbols.length) ? escapeHtml(data.allowed_symbols.join(', ')) : 'الكل'}</div>
        <div class="card-title mt-4">الرموز المحظورة</div>
        <div class="text-sm text-slate-300 mt-2">${(data.blocked_symbols && data.blocked_symbols.length) ? escapeHtml(data.blocked_symbols.join(', ')) : 'لا يوجد'}</div>
      </div>
    </div>`;
  }

  async function renderAdmin(el) {
    try {
      const [health, users, plans, announcements] = await Promise.all([
        api('/api/admin/health'), api('/api/admin/users?limit=20'),
        api('/api/admin/plans'), api('/api/admin/announcements'),
      ]);
      let html = `<div class="page-heading"><div><div class="eyebrow">ADMIN COMMAND CENTER</div><h1 class="page-heading-title">Operations & Access</h1><p class="page-heading-sub">Server-authorized monitoring. No credentials or broker actions are exposed here.</p></div><span class="badge badge-yellow">${health.dry_run ? 'DRY RUN' : 'LIVE BLOCKED BY POLICY'}</span></div>`;
      html += `<div class="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-6"><div class="card"><div class="card-title">Users</div><div class="card-value">${escapeHtml(health.users_total)}</div><div class="card-sub">${escapeHtml(health.users_active)} active</div></div><div class="card"><div class="card-title">Trades</div><div class="card-value">${escapeHtml(health.trades_total)}</div></div><div class="card"><div class="card-title">Signals</div><div class="card-value">${escapeHtml(health.signals_total)}</div></div><div class="card"><div class="card-title">Execution mode</div><div class="card-value text-sm">${health.dry_run ? 'DRY RUN' : 'Unavailable'}</div></div></div>`;
      html += `<div class="card !p-0 overflow-hidden mb-4"><div class="px-4 py-3 border-b border-surface-600"><span class="text-sm font-semibold text-white">Users & readiness</span></div><div class="table-wrap border-0 rounded-none"><table class="data"><thead><tr><th>ID</th><th>Telegram</th><th>Plan</th><th>Trial/MT5</th><th>Status</th></tr></thead><tbody>`;
      for (const u of users.items || []) html += `<tr><td class="mono">${escapeHtml(u.id)}</td><td class="mono">${escapeHtml(u.telegram_id)} ${u.username ? '@' + escapeHtml(u.username) : ''}</td><td><span class="badge badge-blue">${escapeHtml(u.subscription_tier)}</span></td><td>${u.has_gateway ? '<span class="text-profit">MT5 ✓</span>' : '<span class="text-slate-500">Not connected</span>'}</td><td>${u.is_banned ? statusBadge('banned') : u.is_active ? statusBadge('executed') : statusBadge('cancelled')}</td></tr>`;
      html += `</tbody></table></div></div>`;
      html += `<div class="grid lg:grid-cols-2 gap-4"><div class="card"><div class="card-title">Subscription plans</div>${(plans.items || []).length ? `<div class="feature-list">${plans.items.map(plan => `<div><span>${escapeHtml(plan.name)} <small>${escapeHtml(plan.tier)}</small></span><strong>${plan.active ? 'ACTIVE' : 'INACTIVE'}</strong></div>`).join('')}</div>` : '<div class="empty-inline">No plan catalog available.</div>'}</div><div class="card"><div class="card-title">Announcements</div><form id="announcement-form" class="space-y-2"><input id="announcement-title" maxlength="160" placeholder="Title" class="w-full bg-surface-700 border border-surface-600 rounded-xl px-3 py-2 text-sm text-white" required /><textarea id="announcement-message" maxlength="4000" placeholder="Message" class="w-full bg-surface-700 border border-surface-600 rounded-xl px-3 py-2 text-sm text-white" required></textarea><label class="text-xs text-slate-400 flex gap-2 items-center"><input id="announcement-enabled" type="checkbox" /> Enable next daily cycle</label><button class="px-4 py-2 rounded-xl bg-accent-500 text-white text-sm" type="submit">Save announcement</button></form><div class="mt-4 space-y-2">${(announcements.items || []).map(item => `<div class="border border-surface-600 rounded-xl p-3"><div class="text-white text-sm">${escapeHtml(item.title)}</div><div class="text-xs text-slate-400 mt-1">${item.enabled ? 'Enabled' : 'Disabled'} · delivery is restart-safe</div></div>`).join('') || '<div class="empty-inline">No announcements configured.</div>'}</div></div></div>`;
      el.innerHTML = html;
      const form = document.getElementById('announcement-form');
      if (form) form.onsubmit = async event => {
        event.preventDefault();
        const title = document.getElementById('announcement-title').value.trim();
        const message = document.getElementById('announcement-message').value.trim();
        if (!title || !message) return;
        try {
          await api('/api/admin/announcements', {method: 'POST', body: JSON.stringify({title, message, enabled: document.getElementById('announcement-enabled').checked})});
          await renderAdmin(el);
        } catch (_) { alert('تعذر حفظ الإعلان الآن.'); }
      };
    } catch (_) {
      el.innerHTML = errorBox('غير مصرح — صلاحيات الإدارة مطلوبة أو بيانات مركز الإدارة غير متاحة.');
    }
  }

  function updateConnBadge(connected, dryRun) {
    const dot = document.getElementById('conn-dot');
    const label = document.getElementById('conn-label');
    const dry = document.getElementById('dry-run-badge');
    if (connected) {
      dot.className = 'w-1.5 h-1.5 rounded-full bg-profit';
      label.textContent = 'متصل';
    } else {
      dot.className = 'w-1.5 h-1.5 rounded-full bg-loss';
      label.textContent = 'غير متصل';
    }
    if (dryRun) {
      dry.classList.remove('hidden');
      dry.classList.add('inline-flex');
    } else {
      dry.classList.add('hidden');
    }
  }

  // ── Boot ──────────────────────────────────────────────────────────────────
  document.getElementById('login-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const btn = document.getElementById('login-btn');
    const err = document.getElementById('login-error');
    err.classList.add('hidden');
    btn.disabled = true;
    try {
      await login(
        document.getElementById('login-telegram-id').value,
        document.getElementById('login-api-key').value
      );
    } catch (ex) {
      err.textContent = 'تعذر تسجيل الدخول. تحقق من البيانات وحاول مرة أخرى.';
      err.classList.remove('hidden');
    } finally {
      btn.disabled = false;
    }
  });

  document.getElementById('logout-btn').addEventListener('click', logout);
  document.getElementById('menu-btn').addEventListener('click', openSidebar);
  document.getElementById('sidebar-overlay').addEventListener('click', closeSidebar);

  document.querySelectorAll('.nav-item').forEach((el) => {
    el.addEventListener('click', (e) => {
      e.preventDefault();
      location.hash = el.dataset.page;
    });
  });

  window.addEventListener('hashchange', () => {
    if (token || guestMode) navigate(location.hash.slice(1) || 'dashboard');
  });

  // Session restore / Telegram Mini App bootstrap. The browser never supplies
  // a Telegram user id separately; the server validates signed initData.
  (async () => {
    const telegramWebApp = window.Telegram && window.Telegram.WebApp;
    const initData = telegramWebApp && telegramWebApp.initData;
    if (initData) {
      telegramWebApp.ready();
      if (telegramWebApp.expand) telegramWebApp.expand();
      document.getElementById('login-form').classList.add('hidden');
      showTelegramWebAppStatus('جارٍ التحقق من جلسة Telegram…');
      try {
        await loginWithTelegramWebApp(initData);
      } catch (error) {
        enterGuestMode(
          error.status === 403
            ? 'تم فتح Guest Mode. التسجيل وربط MT5 مطلوبان فقط عند اختيار ميزة الحساب.'
            : 'تعذر إنشاء جلسة مستخدم؛ تم فتح Guest Mode للمحتوى العام فقط.'
        );
      }
      return;
    }

    if (telegramWebApp) {
      telegramWebApp.ready();
      enterGuestMode('تم فتح Guest Mode. استخدم /register في بوت Telegram عند الحاجة.');
      return;
    }

    showTelegramWebAppStatus('Please open Tonpo from Telegram.');
    if (!token) {
      enterGuestMode('مرحبًا بك في وضع الاستكشاف. لا تحتاج API Key لتصفح Tonpo.');
      return;
    }
    try {
      currentUser = await api('/api/auth/me');
      showApp();
      applyUserVisibility();
      document.getElementById('sidebar-user').textContent =
        currentUser.username || `ID ${currentUser.telegram_id}`;
      navigate(location.hash.slice(1) || 'dashboard');
    } catch {
      enterGuestMode('انتهت الجلسة السابقة أو لم تعد صالحة؛ تم فتح المحتوى العام بأمان.');
    }
  })();


  // ── WebSocket live updates ────────────────────────────────────────────────
  let _ws = null;
  let _wsRetry = 0;

  function connectWS() {
    if (!token) return;
    try {
      if (_ws && (_ws.readyState === 0 || _ws.readyState === 1)) return;
      const proto = location.protocol === 'https:' ? 'wss' : 'ws';
      const url = proto + '://' + location.host + '/ws';
      _ws = new WebSocket(url);
      _ws.onopen = () => {
        _wsRetry = 0;
        _ws.send(JSON.stringify({ type: 'auth', token }));
      };
      _ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data);
          if (msg.type === 'snapshot' && currentPage === 'dashboard') {
            // Soft refresh dashboard on live snapshot
            renderPage('dashboard');
          }
          if (msg.type === 'connected' && msg.dry_run) {
            const dry = document.getElementById('dry-run-badge');
            if (dry) { dry.classList.remove('hidden'); dry.classList.add('inline-flex'); }
          }
        } catch (_) {}
      };
      _ws.onclose = () => {
        _ws = null;
        const delay = Math.min(30000, 1000 * Math.pow(2, _wsRetry++));
        setTimeout(connectWS, delay);
      };
      _ws.onerror = () => { try { _ws.close(); } catch (_) {} };
    } catch (_) {}
  }

  // Start WS after successful session
  const _origShowApp = showApp;
  // hook: call connectWS when app shown
  const _bootInterval = setInterval(() => {
    if (token && document.getElementById('app') && !document.getElementById('app').classList.contains('hidden')) {
      connectWS();
      clearInterval(_bootInterval);
    }
  }, 1500);

  async function renderSettings(el) {
    const data = await api('/api/settings');
    const configuredMinRisk = Number(data.min_risk_factor);
    const configuredMaxRisk = Number(data.max_risk_factor);
    const validRiskLimits = Number.isFinite(configuredMinRisk) && configuredMinRisk > 0 &&
      Number.isFinite(configuredMaxRisk) && configuredMaxRisk >= configuredMinRisk;
    const minRisk = validRiskLimits ? configuredMinRisk : 0.001;
    const maxRisk = validRiskLimits ? configuredMaxRisk : 0.05;
    const configuredRisk = Number(data.default_risk_factor);
    const currentRisk = Number.isFinite(configuredRisk) ? configuredRisk : 0.01;
    el.innerHTML = `<div class="card max-w-lg space-y-4">
      <div class="flex justify-between"><span class="text-slate-400 text-sm">الخطة</span><span class="badge badge-blue">${escapeHtml(data.subscription_tier || 'free')}</span></div>
      <label class="block text-sm"><span class="text-slate-400">المخاطرة الافتراضية (${minRisk}–${maxRisk})</span>
        <input id="set-risk" type="number" step="any" min="${minRisk}" max="${maxRisk}" value="${currentRisk}"
          class="mt-1 w-full bg-surface-700 border border-surface-600 rounded-xl px-3 py-2 text-white mono" />
      </label>
      <label class="block text-sm"><span class="text-slate-400">اللغة</span>
        <select id="set-lang" class="mt-1 w-full bg-surface-700 border border-surface-600 rounded-xl px-3 py-2 text-white">
          <option value="ar" ${(data.language||'ar')==='ar'?'selected':''}>العربية</option>
          <option value="en" ${data.language==='en'?'selected':''}>English</option>
        </select>
      </label>
      <div class="flex justify-between"><span class="text-slate-400 text-sm">بوابة MT5</span><span class="${data.has_gateway ? 'text-profit' : 'text-loss'}">${data.has_gateway ? 'مربوطة' : 'غير مربوطة'}</span></div>
      <button type="button" id="set-save" class="px-4 py-2 rounded-xl bg-accent-500 text-white text-sm">حفظ</button>
      <div class="pt-2 border-t border-surface-600">
        ${data.dry_run ? '<span class="badge badge-yellow">TRADING_DRY_RUN = true</span>' : '<span class="badge badge-green">Live trading</span>'}
        <p class="text-xs text-slate-500 mt-2">لا يمكن تغيير Dry Run من الواجهة.</p>
      </div>
    </div>`;
    const save = document.getElementById('set-save');
    if (save) save.onclick = async () => {
      const default_risk_factor = parseFloat(document.getElementById('set-risk').value);
      const language = document.getElementById('set-lang').value;
      try {
        await api('/api/settings', { method: 'PATCH', body: JSON.stringify({ default_risk_factor, language }) });
        alert('تم الحفظ');
        renderSettings(el);
      } catch (e) { alert('تعذر حفظ الإعدادات الآن.'); }
    };
  }

  async function renderSignalDetail(el, id) {
    const s = await api('/api/signals/' + encodeURIComponent(id));
    const tps = (s.take_profits || []).join(', ') || '—';
    const timeline = (s.timeline || []).map(item => `
      <li class="flex items-center gap-2 text-sm">
        <span class="w-2 h-2 rounded-full ${item.state === 'complete' || item.state === 'persisted' ? 'bg-profit' : item.state === 'dry_run' || item.state === 'unknown' ? 'bg-amber-400' : 'bg-loss'}"></span>
        <span>${escapeHtml(item.label)}</span><span class="text-xs text-slate-500">${escapeHtml(item.state || 'unknown')}</span>
      </li>`).join('');
    el.innerHTML = `
      <div class="mb-3"><a href="#signals" class="text-xs text-accent-glow">← الإشارات</a></div>
      <div class="card max-w-2xl space-y-3">
        <div class="flex justify-between items-center">
          <span class="text-lg font-semibold text-white mono">${escapeHtml(s.symbol || '—')}</span>
          ${statusBadge(s.status)}
        </div>
        <div class="grid grid-cols-2 gap-3 text-sm">
          <div><span class="text-slate-400">الاتجاه</span><div class="text-white">${escapeHtml(s.direction || '—')}</div></div>
          <div><span class="text-slate-400">المصدر</span><div class="text-white">${escapeHtml(s.source || '—')}</div></div>
          <div><span class="text-slate-400">Entry</span><div class="mono">${escapeHtml(s.entry || '—')}</div></div>
          <div><span class="text-slate-400">Stop Loss</span><div class="mono text-loss">${escapeHtml(s.stop_loss || '—')}</div></div>
          <div class="col-span-2"><span class="text-slate-400">Take Profit</span><div class="mono text-profit">${escapeHtml(tps)}</div></div>
          <div class="col-span-2"><span class="text-slate-400">الوقت</span><div class="mono text-xs">${escapeHtml(s.created_at || '—')}</div></div>
        </div>
        ${s.decision ? `<div class="why-card"><div class="card-title">Why didn't Tonpo trade?</div><div class="text-white font-semibold">${escapeHtml(s.decision.title)}</div><div class="card-sub mt-1">${escapeHtml(s.decision.explanation)}</div><div class="card-sub mt-1">${escapeHtml(s.created_at || '—')} · ${escapeHtml(s.status || '—')}</div></div>` : (s.rejection_reason ? `<div class="why-card"><div class="card-title">Why didn't Tonpo trade?</div><div class="text-white">${escapeHtml(s.rejection_reason)}</div></div>` : '')}
        ${s.news_status ? `<div class="text-xs text-slate-400">حالة الأخبار: ${escapeHtml(s.news_status)}</div>` : ''}
        ${s.reconciliation_required ? '<div class="why-card border-warn/40"><div class="card-title">Manual reconciliation required</div><div class="card-sub">Broker outcome is unknown. Tonpo will not retry this signal automatically. Verify the broker state before any manual action.</div></div>' : ''}
        <pre class="text-xs bg-surface-900 p-3 rounded-lg overflow-x-auto text-slate-300 whitespace-pre-wrap">${escapeHtml(s.signal_text || '')}</pre>
        <div class="border-t border-surface-600 pt-3"><div class="text-sm font-semibold text-white mb-2">Signal timeline</div><ul class="space-y-2">${timeline || '<li class="text-sm text-slate-500">No persisted timeline events</li>'}</ul></div>
        <p class="text-xs text-slate-500">التنفيذ يبدأ فقط من مصدر الإشارة المعتمد ويمر عبر التحقق والاشتراك والمخاطر والـpipeline. هذه الشاشة للمتابعة فقط.</p>
      </div>`;
  }

  async function renderTradeDetail(el, id) {
    const t = await api('/api/trades/' + encodeURIComponent(id));
    const timeline = (t.timeline || []).map(item => `
      <li class="flex items-center gap-2 text-sm">
        <span class="w-2 h-2 rounded-full ${item.state === 'complete' || item.state === 'dry_run' ? 'bg-profit' : item.state === 'failed' || item.state === 'rejected' ? 'bg-loss' : 'bg-slate-500'}"></span>
        <span>${escapeHtml(item.label)}</span><span class="text-xs text-slate-500">${escapeHtml(item.state || 'unknown')}</span>
      </li>`).join('');
    el.innerHTML = `
      <div class="mb-3"><a href="#trades" class="text-xs text-accent-glow">← الصفقات</a></div>
      <div class="card max-w-2xl space-y-3">
        <div class="flex justify-between"><span class="text-lg font-semibold mono text-white">${escapeHtml(t.symbol || '—')}</span>${statusBadge(t.status)}</div>
        <div class="grid grid-cols-2 gap-3 text-sm">
          <div><span class="text-slate-400">النوع</span><div>${escapeHtml(t.order_type || '—')}</div></div>
          <div><span class="text-slate-400">الحجم</span><div class="mono">${escapeHtml(t.volume != null ? t.volume : '—')}</div></div>
          <div><span class="text-slate-400">Entry</span><div class="mono">${escapeHtml(t.entry_price != null ? t.entry_price : '—')}</div></div>
          <div><span class="text-slate-400">SL</span><div class="mono text-loss">${escapeHtml(t.stop_loss != null ? t.stop_loss : '—')}</div></div>
          <div><span class="text-slate-400">TP</span><div class="mono text-profit">${escapeHtml(t.take_profit != null ? t.take_profit : '—')}</div></div>
          <div><span class="text-slate-400">P/L</span><div class="mono">${escapeHtml(t.profit != null ? t.profit : '—')}</div></div>
          <div><span class="text-slate-400">فتح</span><div class="mono text-xs">${escapeHtml(t.created_at || '—')}</div></div>
          <div><span class="text-slate-400">إغلاق</span><div class="mono text-xs">${escapeHtml(t.closed_at || '—')}</div></div>
        </div>
        <div class="border-t border-surface-600 pt-3"><div class="text-sm font-semibold text-white mb-2">Execution timeline</div><ul class="space-y-2">${timeline || '<li class="text-sm text-slate-500">No persisted timeline events</li>'}</ul></div>
        <p class="text-xs text-slate-500">Close/Modify غير متاحين من الويب — استخدم البوت.</p>
      </div>`;
  }

  async function renderSupport(el) {
    const data = await api('/api/support/tickets');
    const items = data.items || [];
    el.innerHTML = `
      <div class="grid lg:grid-cols-2 gap-4">
        <div class="card space-y-3">
          <div class="text-sm font-semibold text-white">تذكرة جديدة</div>
          <input id="sup-subject" class="w-full bg-surface-700 border border-surface-600 rounded-xl px-3 py-2 text-sm text-white" placeholder="الموضوع" maxlength="160" />
          <textarea id="sup-msg" rows="4" class="w-full bg-surface-700 border border-surface-600 rounded-xl px-3 py-2 text-sm text-white" placeholder="الرسالة" maxlength="4000"></textarea>
          <button type="button" id="sup-send" class="px-4 py-2 rounded-xl bg-accent-500 text-white text-sm">إرسال</button>
        </div>
        <div class="card !p-0 overflow-hidden">
          <div class="px-4 py-3 border-b border-surface-600 text-sm font-semibold text-white">تذاكري</div>
          ${items.length ? `<div class="divide-y divide-surface-600">${items.map(t => `
            <div class="px-4 py-3 text-sm"><div class="text-white">${escapeHtml(t.subject)}</div>
            <div class="text-xs text-slate-400 mt-1">${statusBadge(t.status)} · ${escapeHtml(t.created_at || '')}</div></div>`).join('')}</div>`
            : '<div class="p-6 text-center text-slate-500 text-sm">لا توجد تذاكر</div>'}
        </div>
      </div>`;
    const btn = document.getElementById('sup-send');
    if (btn) btn.onclick = async () => {
      const subject = document.getElementById('sup-subject').value.trim();
      const message = document.getElementById('sup-msg').value.trim();
      if (!subject || !message) return alert('أكمل الحقول');
      try {
        await api('/api/support/tickets', { method: 'POST', body: JSON.stringify({ subject, message }) });
        renderSupport(el);
      } catch (e) { alert('تعذر إرسال الطلب الآن.'); }
    };
  }

  function aiAppend(role, text) {
    const box = document.getElementById('ai-messages');
    if (!box) return;
    const div = document.createElement('div');
    div.className = role === 'user' ? 'text-right' : 'text-left';
    div.innerHTML = `<div class="inline-block max-w-[90%] rounded-xl px-3 py-2 text-sm ${role==='user'?'bg-accent-500 text-white':'bg-surface-700 text-slate-200'}" style="white-space:pre-wrap">${escapeHtml(text)}</div>`;
    box.appendChild(div);
    box.scrollTop = box.scrollHeight;
  }

  async function loadAiQuick() {
    const lang = (document.getElementById('ai-lang') || {}).value || 'ar';
    const wrap = document.getElementById('ai-quick');
    if (!wrap) return;
    try {
      const data = await api('/api/assistant/quick-actions?language=' + encodeURIComponent(lang));
      wrap.innerHTML = (data.actions || []).map(a =>
        `<button type="button" class="ai-q text-xs px-2 py-1 rounded-lg bg-surface-700 text-slate-300 hover:bg-surface-600 border border-surface-600">${escapeHtml(a)}</button>`
      ).join('');
      wrap.querySelectorAll('.ai-q').forEach(btn => {
        btn.onclick = () => { document.getElementById('ai-input').value = btn.textContent; document.getElementById('ai-form').requestSubmit(); };
      });
      const input = document.getElementById('ai-input');
      const msgs = document.getElementById('ai-messages');
      if (input) input.dir = lang === 'ar' ? 'rtl' : 'ltr';
      if (msgs) msgs.dir = lang === 'ar' ? 'rtl' : 'ltr';
    } catch (_) {}
  }

  function initAi() {
    const fab = document.getElementById('ai-fab');
    const panel = document.getElementById('ai-panel');
    if (!fab || !panel) return;
    fab.onclick = () => { panel.classList.toggle('hidden'); if (!panel.classList.contains('hidden')) loadAiQuick(); };
    const close = document.getElementById('ai-close');
    if (close) close.onclick = () => panel.classList.add('hidden');
    const langSel = document.getElementById('ai-lang');
    if (langSel) langSel.onchange = loadAiQuick;
    const form = document.getElementById('ai-form');
    if (form) form.onsubmit = async (e) => {
      e.preventDefault();
      const input = document.getElementById('ai-input');
      const msg = input.value.trim();
      if (!msg) return;
      input.value = '';
      aiAppend('user', msg);
      try {
        const lang = document.getElementById('ai-lang').value;
        const r = await api('/api/assistant/chat', { method: 'POST', body: JSON.stringify({ message: msg, language: lang }) });
        aiAppend('bot', r.reply || '—');
      } catch (err) {
        aiAppend('bot', 'تعذر إكمال الطلب الآن.');
      }
    };
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initAi);
  else initAi();

})();
