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
    mt5: 'اتصال MT5',
    risk: 'إدارة المخاطر',
    settings: 'الإعدادات',
    admin: 'لوحة الإدارة',
    support: 'الدعم',
    signal: 'تفاصيل الإشارة',
    trade: 'تفاصيل الصفقة',
  };

  let token = localStorage.getItem('tonpo_token') || '';
  let currentUser = null;
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
    if (!res.ok) throw new Error(data.detail || data.error || `HTTP ${res.status}`);
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

  function logout() {
    token = '';
    currentUser = null;
    localStorage.removeItem('tonpo_token');
    showLogin();
  }

  async function login(telegramId, apiKey) {
    const data = await api('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ telegram_id: Number(telegramId), api_key: apiKey }),
    });
    token = data.access_token;
    currentUser = data.user;
    localStorage.setItem('tonpo_token', token);
    showApp();
    document.getElementById('sidebar-user').textContent =
      currentUser.username || `ID ${currentUser.telegram_id}`;
    navigate(location.hash.slice(1) || 'dashboard');
  }

  // ── Navigation ────────────────────────────────────────────────────────────
  function navigate(page) {
    if (!TITLES[page]) page = 'dashboard';
    currentPage = page;
    document.getElementById('page-title').textContent = TITLES[page];
    document.querySelectorAll('.nav-item').forEach((el) => {
      el.classList.toggle('active', el.dataset.page === page);
    });
    closeSidebar();
    renderPage(page);
  }

  function openSidebar() {
    document.getElementById('sidebar').classList.add('open');
    document.getElementById('sidebar-overlay').classList.add('open');
  }
  function closeSidebar() {
    document.getElementById('sidebar').classList.remove('open');
    document.getElementById('sidebar-overlay').classList.remove('open');
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
  function plClass(n) {
    if (n == null) return '';
    return n >= 0 ? 'text-profit' : 'text-loss';
  }
  function statusBadge(s) {
    const map = {
      executed: 'badge-green', dry_run: 'badge-yellow', partial: 'badge-blue',
      pending: 'badge-blue', confirmation_required: 'badge-yellow',
      manual_review: 'badge-yellow', failed: 'badge-red', rejected: 'badge-red',
      invalid: 'badge-red', cancelled: 'badge-gray', received: 'badge-gray',
      unauthorized: 'badge-red', duplicate: 'badge-gray',
    };
    const cls = map[s] || 'badge-gray';
    return `<span class="badge ${cls}">${s || '—'}</span>`;
  }
  function skeleton(rows = 4) {
    return Array.from({ length: rows }, () =>
      `<div class="skeleton mb-2" style="height:2.5rem"></div>`
    ).join('');
  }
  function empty(msg) {
    return `<div class="empty-state">
      <svg class="w-12 h-12" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1" d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4"/></svg>
      <p>${msg}</p>
    </div>`;
  }
  function errorBox(msg) {
    return `<div class="card border-loss/30 bg-loss/5 text-loss text-sm">${msg}</div>`;
  }

  // ── Pages ─────────────────────────────────────────────────────────────────
  async function renderPage(page) {
    const el = document.getElementById('content');
    el.innerHTML = skeleton(6);
    try {
      if (page === 'dashboard') await renderDashboard(el);
      else if (page === 'signals') await renderSignals(el);
      else if (page === 'trades') await renderTrades(el);
      else if (page === 'mt5') await renderMT5(el);
      else if (page === 'risk') await renderRisk(el);
      else if (page === 'settings') await renderSettings(el);
      else if (page === 'support') await renderSupport(el);
      else if (page === 'admin') await renderAdmin(el);
      else if (page.startsWith('signal/')) await renderSignalDetail(el, page.split('/')[1]);
      else if (page.startsWith('trade/')) await renderTradeDetail(el, page.split('/')[1]);
    } catch (e) {
      el.innerHTML = errorBox(e.message || 'فشل التحميل');
    }
  }

  async function renderDashboard(el) {
    const data = await api('/api/dashboard');
    const a = data.account || {};
    updateConnBadge(a.connected, data.dry_run);

    const cards = [
      { title: 'الرصيد', value: money(a.balance, a.currency), sub: a.connected ? 'متصل' : (a.error || 'غير متصل') },
      { title: 'الأسهم (Equity)', value: money(a.equity, a.currency) },
      { title: 'الهامش المتاح', value: money(a.free_margin, a.currency) },
      { title: 'ربح/خسارة اليوم', value: money(a.daily_pl), cls: plClass(a.daily_pl) },
      { title: 'إجمالي P/L', value: money(a.total_pl), cls: plClass(a.total_pl) },
      { title: 'نسبة الفوز', value: a.win_rate != null ? a.win_rate + '%' : '—' },
      { title: 'صفقات مفتوحة', value: a.open_positions ?? '—' },
      { title: 'الوضع', value: data.dry_run ? 'Dry Run' : 'Live', sub: data.dry_run ? 'لا أوامر حقيقية' : '' },
    ];

    let html = `<div class="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-6">`;
    for (const c of cards) {
      html += `<div class="card">
        <div class="card-title">${c.title}</div>
        <div class="card-value ${c.cls || ''}">${c.value}</div>
        ${c.sub ? `<div class="card-sub">${c.sub}</div>` : ''}
      </div>`;
    }
    html += `</div>`;

    // Per-user trading mode badge + control
    const mode = data.trading_mode || (data.user && data.user.trading_mode) || 'demo';
    const modeBadge = mode === 'live'
      ? '<span class="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 text-sm font-semibold">🟢 LIVE TRADING</span>'
      : '<span class="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-sky-500/15 text-sky-400 border border-sky-500/30 text-sm font-semibold">🔵 DEMO TRADING</span>';
    html += `<div class="card mb-4 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
      <div>
        <div class="text-xs text-slate-400 mb-1">وضع التداول (لكل مستخدم)</div>
        <div id="trading-mode-badge">${modeBadge}</div>
        <p class="text-xs text-slate-500 mt-2">TRADING_DRY_RUN على الخادم يمنع الأوامر الحقيقية حتى في LIVE.</p>
      </div>
      <div class="flex gap-2">
        <button type="button" id="btn-mode-demo" class="px-3 py-2 rounded-xl text-sm border border-surface-600 ${mode==='demo'?'bg-sky-500/20 text-sky-300':'bg-surface-700 text-slate-300'}">DEMO</button>
        <button type="button" id="btn-mode-live" class="px-3 py-2 rounded-xl text-sm border border-surface-600 ${mode==='live'?'bg-emerald-500/20 text-emerald-300':'bg-surface-700 text-slate-300'}">LIVE</button>
      </div>
    </div>
    <div id="live-confirm-modal" class="hidden fixed inset-0 z-[60] flex items-center justify-center bg-black/60 p-4">
      <div class="bg-surface-800 border border-surface-600 rounded-2xl max-w-md w-full p-5 space-y-3">
        <div class="text-lg font-semibold text-white">تأكيد التحويل إلى LIVE</div>
        <p class="text-sm text-slate-300">LIVE يعني تفضيل التداول الحقيقي لحسابك عندما تسمح بيئة الخادم. مع <span class="badge badge-yellow">TRADING_DRY_RUN</span> لن تُرسل أوامر حقيقية الآن.</p>
        <p class="text-sm text-loss">هل تريد المتابعة؟</p>
        <div class="flex gap-2 justify-end">
          <button type="button" id="live-cancel" class="px-3 py-2 rounded-xl bg-surface-700 text-slate-300 text-sm">إلغاء</button>
          <button type="button" id="live-confirm" class="px-3 py-2 rounded-xl bg-emerald-600 text-white text-sm font-semibold">تأكيد LIVE</button>
        </div>
      </div>
    </div>`;

    // Recent signals
    html += `<div class="grid lg:grid-cols-2 gap-4">`;
    html += `<div class="card !p-0 overflow-hidden">
      <div class="px-4 py-3 border-b border-surface-600 flex justify-between items-center">
        <span class="text-sm font-semibold text-white">آخر الإشارات</span>
        <a href="#signals" class="text-xs text-accent-glow">عرض الكل</a>
      </div>`;
    if (!data.recent_signals || !data.recent_signals.length) {
      html += empty('لا توجد إشارات بعد');
    } else {
      html += `<div class="table-wrap border-0 rounded-none"><table class="data"><thead><tr>
        <th>المصدر</th><th>الحالة</th><th>الوقت</th>
      </tr></thead><tbody>`;
      for (const s of data.recent_signals.slice(0, 8)) {
        html += `<tr>
          <td class="mono text-xs">${s.source}</td>
          <td>${statusBadge(s.status)}</td>
          <td class="text-slate-500 text-xs">${s.created_at ? new Date(s.created_at).toLocaleString('ar') : '—'}</td>
        </tr>`;
      }
      html += `</tbody></table></div>`;
    }
    html += `</div>`;

    // Recent trades
    html += `<div class="card !p-0 overflow-hidden">
      <div class="px-4 py-3 border-b border-surface-600 flex justify-between items-center">
        <span class="text-sm font-semibold text-white">آخر الصفقات</span>
        <a href="#trades" class="text-xs text-accent-glow">عرض الكل</a>
      </div>`;
    if (!data.recent_trades || !data.recent_trades.length) {
      html += empty('لا توجد صفقات بعد');
    } else {
      html += `<div class="table-wrap border-0 rounded-none"><table class="data"><thead><tr>
        <th>الرمز</th><th>النوع</th><th>الحجم</th><th>الحالة</th>
      </tr></thead><tbody>`;
      for (const t of data.recent_trades.slice(0, 8)) {
        html += `<tr>
          <td class="mono font-medium text-white">${t.symbol}</td>
          <td>${t.order_type}</td>
          <td class="mono">${t.position_size ?? '—'}</td>
          <td>${statusBadge(t.status)}</td>
        </tr>`;
      }
      html += `</tbody></table></div>`;
    }
    html += `</div></div>`;

    el.innerHTML = html;
    const demoBtn = document.getElementById('btn-mode-demo');
    const liveBtn = document.getElementById('btn-mode-live');
    const modal = document.getElementById('live-confirm-modal');
    if (demoBtn) demoBtn.onclick = async () => {
      try {
        await api('/api/trading-mode', { method: 'PATCH', body: JSON.stringify({ mode: 'demo' }) });
        renderDashboard(el);
      } catch (e) { alert(e.message || 'فشل'); }
    };
    if (liveBtn) liveBtn.onclick = () => { if (modal) modal.classList.remove('hidden'); };
    const cancel = document.getElementById('live-cancel');
    const confirm = document.getElementById('live-confirm');
    if (cancel) cancel.onclick = () => { if (modal) modal.classList.add('hidden'); };
    if (confirm) confirm.onclick = async () => {
      try {
        await api('/api/trading-mode', { method: 'PATCH', body: JSON.stringify({ mode: 'live', confirm_live: true }) });
        if (modal) modal.classList.add('hidden');
        renderDashboard(el);
      } catch (e) { alert(e.message || 'فشل'); }
    };
  }

  async function renderSignals(el) {
    const data = await api('/api/signals?limit=50');
    if (!data.items || !data.items.length) {
      el.innerHTML = empty('لا توجد إشارات بعد — أرسل إشارة من TradingView');
      return;
    }
    let html = `<div class="card !p-0 overflow-hidden">
      <div class="px-4 py-3 border-b border-surface-600">
        <span class="text-sm font-semibold text-white">الإشارات (${data.total})</span>
      </div>
      <div class="table-wrap border-0 rounded-none"><table class="data"><thead><tr>
        <th>الرمز</th><th>الاتجاه</th><th>الدخول</th><th>SL</th><th>TP</th><th>المصدر</th><th>الحالة</th><th>الوقت</th>
      </tr></thead><tbody>`;
    for (const s of data.items) {
      html += `<tr class="cursor-pointer hover:bg-surface-700/40" onclick="location.hash='signal/${s.id}'">
        <td class="mono font-medium text-white">${s.symbol || '—'}</td>
        <td>${s.direction ? `<span class="badge ${s.direction.includes('BUY') || s.direction.includes('Buy') ? 'badge-green' : 'badge-red'}">${s.direction}</span>` : '—'}</td>
        <td class="mono">${s.entry || '—'}</td>
        <td class="mono">${s.stop_loss || '—'}</td>
        <td class="mono text-xs">${(s.take_profits || []).join(', ') || '—'}</td>
        <td class="text-xs">${s.source}</td>
        <td>${statusBadge(s.status)}</td>
        <td class="text-slate-500 text-xs whitespace-nowrap">${s.created_at ? new Date(s.created_at).toLocaleString('ar') : '—'}</td>
      </tr>`;
    }
    html += `</tbody></table></div></div>`;
    el.innerHTML = html;
  }

  async function renderTrades(el) {
    const data = await api('/api/trades?limit=50');
    if (!data.items || !data.items.length) {
      el.innerHTML = empty('لا توجد صفقات بعد');
      return;
    }
    let html = `<div class="card !p-0 overflow-hidden">
      <div class="px-4 py-3 border-b border-surface-600">
        <span class="text-sm font-semibold text-white">الصفقات (${data.total})</span>
      </div>
      <div class="table-wrap border-0 rounded-none"><table class="data"><thead><tr>
        <th>الرمز</th><th>النوع</th><th>الدخول</th><th>الحجم</th><th>المخاطرة</th><th>الحالة</th><th>الوقت</th>
      </tr></thead><tbody>`;
    for (const t of data.items) {
      html += `<tr class="cursor-pointer hover:bg-surface-700/40" onclick="location.hash='trade/${t.id}'">
        <td class="mono font-medium text-white">${t.symbol}</td>
        <td>${t.order_type}</td>
        <td class="mono">${t.entry_price ?? '—'}</td>
        <td class="mono">${t.position_size ?? '—'}</td>
        <td class="mono">${t.risk_percentage != null ? t.risk_percentage + '%' : '—'}</td>
        <td>${statusBadge(t.status)}</td>
        <td class="text-slate-500 text-xs whitespace-nowrap">${t.created_at ? new Date(t.created_at).toLocaleString('ar') : '—'}</td>
      </tr>`;
    }
    html += `</tbody></table></div></div>`;
    el.innerHTML = html;
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
      <div class="card-sub mt-2">${data.message || ''}</div>
      ${data.dry_run ? '<div class="mt-3"><span class="badge badge-yellow">DRY RUN — لا أوامر حقيقية</span></div>' : ''}
    </div>`;
    html += `<div class="card space-y-3">
      <div class="flex justify-between"><span class="text-slate-400 text-sm">الحساب</span><span class="mono text-white">${data.account || '—'}</span></div>
      <div class="flex justify-between"><span class="text-slate-400 text-sm">الوسيط</span><span class="mono text-white">${data.broker || '—'}</span></div>
      <div class="flex justify-between"><span class="text-slate-400 text-sm">الرصيد</span><span class="mono text-white">${money(data.balance)}</span></div>
      <div class="flex justify-between"><span class="text-slate-400 text-sm">الأسهم</span><span class="mono text-white">${money(data.equity)}</span></div>
      <div class="flex justify-between"><span class="text-slate-400 text-sm">الهامش</span><span class="mono text-white">${money(data.margin)}</span></div>
      <div class="flex justify-between"><span class="text-slate-400 text-sm">آخر نبضة</span><span class="mono text-xs text-slate-400">${data.last_heartbeat ? new Date(data.last_heartbeat).toLocaleString('ar') : '—'}</span></div>
    </div></div>`;
    if (data.errors && data.errors.length) {
      html += `<div class="card border-loss/30 bg-loss/5 mt-4">
        <div class="card-title text-loss">أخطاء الاتصال</div>
        <ul class="text-sm text-loss/90 space-y-1 mt-2">${data.errors.map(e => `<li>• ${e}</li>`).join('')}</ul>
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
        <div class="flex justify-between"><span class="text-slate-400 text-sm">أقصى خسارة يومية</span><span class="mono">${data.max_daily_loss ?? '—'}</span></div>
        <div class="flex justify-between"><span class="text-slate-400 text-sm">أقصى صفقات مفتوحة</span><span class="mono">${data.max_open_trades ?? '—'}</span></div>
        <div class="flex justify-between"><span class="text-slate-400 text-sm">أقصى سبريد</span><span class="mono">${data.max_spread ?? '—'}</span></div>
        <div class="pt-2">${data.dry_run ? '<span class="badge badge-yellow">DRY RUN نشط</span>' : '<span class="badge badge-green">Live</span>'}</div>
      </div>
      <div class="card">
        <div class="card-title">الرموز المسموحة</div>
        <div class="text-sm text-slate-300 mt-2">${(data.allowed_symbols && data.allowed_symbols.length) ? data.allowed_symbols.join(', ') : 'الكل'}</div>
        <div class="card-title mt-4">الرموز المحظورة</div>
        <div class="text-sm text-slate-300 mt-2">${(data.blocked_symbols && data.blocked_symbols.length) ? data.blocked_symbols.join(', ') : 'لا يوجد'}</div>
      </div>
    </div>`;
  }

  async function renderAdmin(el) {
    try {
      const health = await api('/api/admin/health');
      const users = await api('/api/admin/users?limit=20');
      let html = `<div class="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-6">
        <div class="card"><div class="card-title">المستخدمون</div><div class="card-value">${health.users_total}</div><div class="card-sub">${health.users_active} نشط</div></div>
        <div class="card"><div class="card-title">الصفقات</div><div class="card-value">${health.trades_total}</div></div>
        <div class="card"><div class="card-title">الإشارات</div><div class="card-value">${health.signals_total}</div></div>
        <div class="card"><div class="card-title">الوضع</div><div class="card-value text-sm">${health.dry_run ? 'Dry Run' : 'Live'}</div></div>
      </div>`;
      html += `<div class="card !p-0 overflow-hidden">
        <div class="px-4 py-3 border-b border-surface-600"><span class="text-sm font-semibold text-white">المستخدمون</span></div>
        <div class="table-wrap border-0 rounded-none"><table class="data"><thead><tr>
          <th>ID</th><th>Telegram</th><th>الخطة</th><th>Gateway</th><th>الحالة</th>
        </tr></thead><tbody>`;
      for (const u of users.items || []) {
        html += `<tr>
          <td class="mono">${u.id}</td>
          <td class="mono">${u.telegram_id} ${u.username ? '@' + u.username : ''}</td>
          <td><span class="badge badge-blue">${u.subscription_tier}</span></td>
          <td>${u.has_gateway ? '<span class="text-profit">✓</span>' : '—'}</td>
          <td>${u.is_banned ? statusBadge('banned') : u.is_active ? statusBadge('executed') : statusBadge('cancelled')}</td>
        </tr>`;
      }
      html += `</tbody></table></div></div>`;
      el.innerHTML = html;
    } catch (e) {
      el.innerHTML = errorBox('غير مصرح — صلاحيات الإدارة مطلوبة');
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
      err.textContent = ex.message || 'فشل تسجيل الدخول';
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
    if (token) navigate(location.hash.slice(1) || 'dashboard');
  });

  // Session restore
  (async () => {
    if (!token) {
      showLogin();
      return;
    }
    try {
      currentUser = await api('/api/auth/me');
      showApp();
      document.getElementById('sidebar-user').textContent =
        currentUser.username || `ID ${currentUser.telegram_id}`;
      navigate(location.hash.slice(1) || 'dashboard');
    } catch {
      logout();
    }
  })();
})();


  // ── WebSocket live updates ────────────────────────────────────────────────
  let _ws = null;
  let _wsRetry = 0;

  function connectWS() {
    if (!token) return;
    try {
      if (_ws && (_ws.readyState === 0 || _ws.readyState === 1)) return;
      const proto = location.protocol === 'https:' ? 'wss' : 'ws';
      const url = proto + '://' + location.host + '/ws?token=' + encodeURIComponent(token);
      _ws = new WebSocket(url);
      _ws.onopen = () => { _wsRetry = 0; };
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
    el.innerHTML = `<div class="card max-w-lg space-y-4">
      <div class="flex justify-between"><span class="text-slate-400 text-sm">الخطة</span><span class="badge badge-blue">${data.subscription_tier || 'free'}</span></div>
      <label class="block text-sm"><span class="text-slate-400">المخاطرة الافتراضية (0.001–0.1)</span>
        <input id="set-risk" type="number" step="0.001" min="0.001" max="0.1" value="${data.default_risk_factor || 0.01}"
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
      } catch (e) { alert(e.message || 'فشل الحفظ'); }
    };
  }

  async function renderSignalDetail(el, id) {
    const s = await api('/api/signals/' + id);
    const tps = (s.take_profits || []).join(', ') || '—';
    el.innerHTML = `
      <div class="mb-3"><a href="#signals" class="text-xs text-accent-glow">← الإشارات</a></div>
      <div class="card max-w-2xl space-y-3">
        <div class="flex justify-between items-center">
          <span class="text-lg font-semibold text-white mono">${s.symbol || '—'}</span>
          ${statusBadge(s.status)}
        </div>
        <div class="grid grid-cols-2 gap-3 text-sm">
          <div><span class="text-slate-400">الاتجاه</span><div class="text-white">${s.direction || '—'}</div></div>
          <div><span class="text-slate-400">المصدر</span><div class="text-white">${s.source || '—'}</div></div>
          <div><span class="text-slate-400">Entry</span><div class="mono">${s.entry || '—'}</div></div>
          <div><span class="text-slate-400">Stop Loss</span><div class="mono text-loss">${s.stop_loss || '—'}</div></div>
          <div class="col-span-2"><span class="text-slate-400">Take Profit</span><div class="mono text-profit">${tps}</div></div>
          <div class="col-span-2"><span class="text-slate-400">الوقت</span><div class="mono text-xs">${s.created_at || '—'}</div></div>
        </div>
        <pre class="text-xs bg-surface-900 p-3 rounded-lg overflow-x-auto text-slate-300 whitespace-pre-wrap">${(s.signal_text || '').replace(/</g,'&lt;')}</pre>
        <button type="button" id="btn-manual-exec" class="px-4 py-2 rounded-xl bg-accent-500 text-white text-sm hover:bg-accent-400">طلب تنفيذ (Dry Run)</button>
        <p class="text-xs text-slate-500">يمر عبر الحماية ويحترم TRADING_DRY_RUN.</p>
      </div>`;
    const btn = document.getElementById('btn-manual-exec');
    if (btn) btn.onclick = async () => {
      try {
        const r = await api('/api/signals/' + id + '/manual-execute', { method: 'POST', body: '{}' });
        alert('النتيجة: ' + (r.status || '') + (r.dry_run ? ' (dry_run)' : ''));
        renderPage('signal/' + id);
      } catch (e) { alert(e.message || 'فشل'); }
    };
  }

  async function renderTradeDetail(el, id) {
    const t = await api('/api/trades/' + id);
    el.innerHTML = `
      <div class="mb-3"><a href="#trades" class="text-xs text-accent-glow">← الصفقات</a></div>
      <div class="card max-w-2xl space-y-3">
        <div class="flex justify-between"><span class="text-lg font-semibold mono text-white">${t.symbol || '—'}</span>${statusBadge(t.status)}</div>
        <div class="grid grid-cols-2 gap-3 text-sm">
          <div><span class="text-slate-400">النوع</span><div>${t.order_type || '—'}</div></div>
          <div><span class="text-slate-400">الحجم</span><div class="mono">${t.volume != null ? t.volume : '—'}</div></div>
          <div><span class="text-slate-400">Entry</span><div class="mono">${t.entry_price != null ? t.entry_price : '—'}</div></div>
          <div><span class="text-slate-400">SL</span><div class="mono text-loss">${t.stop_loss != null ? t.stop_loss : '—'}</div></div>
          <div><span class="text-slate-400">TP</span><div class="mono text-profit">${t.take_profit != null ? t.take_profit : '—'}</div></div>
          <div><span class="text-slate-400">P/L</span><div class="mono">${t.profit != null ? t.profit : '—'}</div></div>
          <div><span class="text-slate-400">فتح</span><div class="mono text-xs">${t.created_at || '—'}</div></div>
          <div><span class="text-slate-400">إغلاق</span><div class="mono text-xs">${t.closed_at || '—'}</div></div>
        </div>
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
            <div class="px-4 py-3 text-sm"><div class="text-white">${t.subject}</div>
            <div class="text-xs text-slate-400 mt-1">${statusBadge(t.status)} · ${t.created_at || ''}</div></div>`).join('')}</div>`
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
      } catch (e) { alert(e.message || 'فشل'); }
    };
  }

  function aiAppend(role, text) {
    const box = document.getElementById('ai-messages');
    if (!box) return;
    const div = document.createElement('div');
    div.className = role === 'user' ? 'text-right' : 'text-left';
    div.innerHTML = `<div class="inline-block max-w-[90%] rounded-xl px-3 py-2 text-sm ${role==='user'?'bg-accent-500 text-white':'bg-surface-700 text-slate-200'}" style="white-space:pre-wrap">${String(text).replace(/</g,'&lt;')}</div>`;
    box.appendChild(div);
    box.scrollTop = box.scrollHeight;
  }

  async function loadAiQuick() {
    const lang = (document.getElementById('ai-lang') || {}).value || 'ar';
    const wrap = document.getElementById('ai-quick');
    if (!wrap || !token) return;
    try {
      const data = await api('/api/assistant/quick-actions?language=' + lang);
      wrap.innerHTML = (data.actions || []).map(a =>
        `<button type="button" class="ai-q text-xs px-2 py-1 rounded-lg bg-surface-700 text-slate-300 hover:bg-surface-600 border border-surface-600">${String(a).replace(/</g,'&lt;')}</button>`
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
      if (!token) { alert('سجّل الدخول أولاً'); return; }
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
        aiAppend('bot', err.message || 'Error');
      }
    };
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initAi);
  else initAi();
