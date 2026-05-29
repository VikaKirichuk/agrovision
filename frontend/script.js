// ─── CONFIG ───
const API = 'http://localhost:8000';

// ─── STATE ───
let isLoggedIn  = false;
let isAdmin     = false;
let userName    = '';
let authToken   = '';
let currentPage = 'home';
let pendingPage = null;
let uploadedFile = null;

// ─── AUTO-LOGOUT: бездіяльність ───
let inactivityTimer = null;
const INACTIVITY_TIMEOUT = 15 * 60 * 1000; // 15 хвилин

function resetInactivityTimer() {
  if (!isLoggedIn) return;
  clearTimeout(inactivityTimer);
  inactivityTimer = setTimeout(() => {
    showToast('Сесію завершено через бездіяльність 🔒', 'info');
    doLogout();
  }, INACTIVITY_TIMEOUT);
}
function startInactivityWatcher() {
  ['mousemove','keydown','click','touchstart','scroll'].forEach(evt =>
    document.addEventListener(evt, resetInactivityTimer, { passive: true })
  );
  resetInactivityTimer();
}
function stopInactivityWatcher() {
  clearTimeout(inactivityTimer);
}

// ─── CLOSE TAB = LOGOUT ───
// sessionStorage автоматично очищається при закритті вкладки
// Але ще явно чистимо через beforeunload для надійності
window.addEventListener('beforeunload', () => {
  if (isLoggedIn) {
    sessionStorage.removeItem('agro_token');
    sessionStorage.removeItem('agro_user');
    sessionStorage.removeItem('agro_is_admin');
  }
});

// ─── КЛАСИ ───
const CLASSES = [
  'double_plant','drydown','endrow','nutrient_deficiency',
  'planter_skip','storm_damage','water','waterway','weed_cluster'
];
const LABELS_UA = {
  double_plant:        '🌱 Подвійне посадження',
  drydown:             '🏜️ Висихання рослин',
  endrow:              '↩️ Пошкодження кінця ряду',
  nutrient_deficiency: '🟡 Нестача поживних речовин',
  planter_skip:        '⬜ Зріджені рослини',
  storm_damage:        '⛈️ Пошкодження бурею',
  water:               '💧 Застій води',
  waterway:            '🌊 Водотік',
  weed_cluster:        "🌿 Бур'яни",
};
const COLORS = [
  '#6464ff','#ffc800','#64ff64','#00ffff','#c864ff',
  '#ff6400','#0064ff','#00ffc8','#64ffc8'
];

// ════════════════════════════════════════
//  TOAST
// ════════════════════════════════════════
function showToast(msg, type = 'error') {
  let container = document.getElementById('toast-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toast-container';
    container.style.cssText =
      'position:fixed;top:1.2rem;right:1.2rem;z-index:9999;display:flex;flex-direction:column;gap:.5rem;pointer-events:none;';
    document.body.appendChild(container);
  }
  const colors = { success:'#2d6a4f', info:'#1a3a5c', error:'#7a1c1c' };
  const toast = document.createElement('div');
  toast.style.cssText =
    `background:${colors[type]||colors.error};color:#fff;padding:.75rem 1.2rem;border-radius:8px;
     font-size:.9rem;max-width:320px;box-shadow:0 4px 16px rgba(0,0,0,.4);
     animation:fadeInRight .25s ease;pointer-events:auto;`;
  toast.textContent = msg;
  container.appendChild(toast);
  setTimeout(() => { toast.style.opacity='0'; toast.style.transition='opacity .3s'; }, 3700);
  setTimeout(() => toast.remove(), 4000);
}

// ════════════════════════════════════════
//  SESSION — sessionStorage (закриття вкладки = вихід)
// ════════════════════════════════════════
function saveSession() {
  sessionStorage.setItem('agro_token', authToken);
  sessionStorage.setItem('agro_user', userName);
  sessionStorage.setItem('agro_is_admin', isAdmin ? '1' : '0');
}
function clearSession() {
  sessionStorage.removeItem('agro_token');
  sessionStorage.removeItem('agro_user');
  sessionStorage.removeItem('agro_is_admin');
  // Чистимо старий localStorage якщо є
  localStorage.removeItem('agro_token');
  localStorage.removeItem('agro_user');
  localStorage.removeItem('agro_is_admin');
}
function restoreSession() {
  const token = sessionStorage.getItem('agro_token');
  const name  = sessionStorage.getItem('agro_user');
  const admin = sessionStorage.getItem('agro_is_admin') === '1';
  if (token && name) {
    authToken = token; userName = name; isAdmin = admin; isLoggedIn = true;
    updateNavForLoggedIn();
    showPage('analysis');
    startInactivityWatcher();
  }
}

// ════════════════════════════════════════
//  НАВ-БАР: показати стан залогіненого
// ════════════════════════════════════════
function updateNavForLoggedIn() {
  const authBtn = document.getElementById('btn-auth');

  if (isLoggedIn) {
    // Кнопка з іменем — просто відображення, не клікабельна
    authBtn.innerHTML = `<span style="font-size:.85rem;opacity:.6;margin-right:.25rem">👤</span>${userName}`;
    authBtn.className = 'nav-btn user-name-btn';
    authBtn.onclick = null; // без дії при кліку

    // Додаємо кнопку "Вийти" якщо ще немає
    if (!document.getElementById('btn-logout')) {
      const logoutBtn = document.createElement('button');
      logoutBtn.id = 'btn-logout';
      logoutBtn.className = 'nav-btn logout-btn';
      logoutBtn.textContent = '🚪 Вийти';
      logoutBtn.onclick = openLogoutModal;
      document.querySelector('.nav-links').appendChild(logoutBtn);
    }

    // Кнопка адміна
    _showAdminNav();

  } else {
    // Повертаємо кнопку авторизації
    authBtn.textContent = 'Авторизація / Реєстрація';
    authBtn.className = 'nav-btn primary';
    authBtn.onclick = openAuth;

    // Прибираємо кнопку виходу
    document.getElementById('btn-logout')?.remove();
    document.getElementById('btn-admin-panel')?.remove();
  }
}

// ════════════════════════════════════════
//  LOGOUT MODAL — підтвердження виходу
// ════════════════════════════════════════
function openLogoutModal() {
  document.getElementById('logout-modal').classList.add('active');
}
function closeLogoutModal() {
  document.getElementById('logout-modal').classList.remove('active');
}
function confirmLogout() {
  closeLogoutModal();
  doLogout();
}

// ════════════════════════════════════════
//  LEGEND
// ════════════════════════════════════════
document.addEventListener('DOMContentLoaded', () => {
  const legendBar = document.getElementById('legend-bar');
  if (legendBar) {
    CLASSES.forEach((cls, i) => {
      const el = document.createElement('div');
      el.className = 'legend-item';
      el.innerHTML = `<div class="legend-dot" style="background:${COLORS[i]}"></div>${LABELS_UA[cls]}`;
      legendBar.appendChild(el);
    });
  }
  initDragDrop();
  restoreSession();

  // Закриття logout modal при кліку на фон
  document.getElementById('logout-modal')?.addEventListener('click', function(e) {
    if (e.target === this) closeLogoutModal();
  });
  // Закриття auth modal при кліку на фон
  document.getElementById('auth-modal')?.addEventListener('click', function(e) {
    if (e.target === this) closeAuth();
  });
});

// ════════════════════════════════════════
//  PAGE ROUTING
// ════════════════════════════════════════
function showPage(name) {
  if (name === 'admin') {
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.getElementById('page-admin').classList.add('active');
    loadAdminData();
    return;
  }
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.getElementById('page-' + name).classList.add('active');
  currentPage = name;
  document.querySelectorAll('.nav-btn[id^=btn-]').forEach(b => b.classList.remove('active'));
  if (name === 'home')    document.getElementById('btn-about')?.classList.add('active');
  if (name === 'history') { document.getElementById('btn-history')?.classList.add('active'); loadHistory(); }
}
function goHome()          { showPage(isLoggedIn ? 'analysis' : 'home'); }
function requireAuth(page) {
  if (page === 'admin' && !isAdmin) { showToast('Немає доступу'); return; }
  if (isLoggedIn) showPage(page);
  else { pendingPage = page; openAuth(); }
}

// ════════════════════════════════════════
//  AUTH MODAL
// ════════════════════════════════════════
function openAuth()  { document.getElementById('auth-modal').classList.add('active'); }
function closeAuth() { document.getElementById('auth-modal').classList.remove('active'); pendingPage = null; }
function switchTab(tab) {
  document.getElementById('tab-login').classList.toggle('active', tab === 'login');
  document.getElementById('tab-reg').classList.toggle('active',   tab === 'register');
  document.getElementById('form-login').style.display    = tab === 'login'    ? 'block' : 'none';
  document.getElementById('form-register').style.display = tab === 'register' ? 'block' : 'none';
}

// ════════════════════════════════════════
//  ВАЛІДАЦІЯ
// ════════════════════════════════════════
function setError(id, msg) {
  const el = document.getElementById('err-' + id);
  if (el) { el.textContent = msg; el.style.display = msg ? 'block' : 'none'; }
  const input = document.getElementById(id);
  if (input) {
    input.classList.toggle('input-error', !!msg);
    if (!msg) input.classList.add('input-ok');
    else      input.classList.remove('input-ok');
  }
}
function clearFieldError(id) { setError(id, ''); }

function isValidEmail(v) {
  return /^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$/.test(v.trim());
}
function isValidPhone(v) {
  const c = v.replace(/[\s\-\(\)]/g, '');
  return !c || /^(\+380\d{9}|0\d{9})$/.test(c);
}
function validateEmailField(inputId, errId) {
  const val = document.getElementById(inputId).value.trim();
  const el  = document.getElementById(errId);
  if (!el) return;
  if (!val) { el.textContent = ''; el.style.display = 'none'; return; }
  const ok = isValidEmail(val);
  el.textContent = ok ? '' : 'Невірний формат (приклад: name@gmail.com)';
  el.style.display = ok ? 'none' : 'block';
  document.getElementById(inputId).classList.toggle('input-error', !ok);
  document.getElementById(inputId).classList.toggle('input-ok', ok);
}
function validatePhoneField(inputId, errId) {
  const val = document.getElementById(inputId).value.trim();
  const el  = document.getElementById(errId);
  if (!el) return;
  if (!val) { el.textContent = ''; el.style.display = 'none'; return; }
  const ok = isValidPhone(val);
  el.textContent = ok ? '' : 'Формат: +380681234567 або 0681234567';
  el.style.display = ok ? 'none' : 'block';
  document.getElementById(inputId).classList.toggle('input-error', !ok);
  document.getElementById(inputId).classList.toggle('input-ok', ok);
}
function validatePassField() {
  const val  = document.getElementById('reg-pass').value;
  const bar  = document.getElementById('pass-strength');
  const fill = document.getElementById('strength-fill');
  const lbl  = document.getElementById('strength-label');
  clearFieldError('reg-pass');
  validatePass2Field();
  if (!val) { bar.style.display = 'none'; return; }
  bar.style.display = 'flex';
  let score = 0;
  if (val.length >= 6)           score++;
  if (val.length >= 10)          score++;
  if (/[A-Z]/.test(val))         score++;
  if (/[0-9]/.test(val))         score++;
  if (/[^A-Za-z0-9]/.test(val))  score++;
  const levels = [
    { pct:'20%', color:'#e74c3c', text:'Дуже слабкий' },
    { pct:'40%', color:'#e67e22', text:'Слабкий' },
    { pct:'60%', color:'#f1c40f', text:'Середній' },
    { pct:'80%', color:'#2ecc71', text:'Сильний' },
    { pct:'100%',color:'#27ae60', text:'Відмінний' },
  ];
  const lvl = levels[Math.min(score-1,4)] || levels[0];
  fill.style.width = lvl.pct; fill.style.background = lvl.color;
  lbl.textContent = lvl.text; lbl.style.color = lvl.color;
}
function validatePass2Field() {
  const p1 = document.getElementById('reg-pass').value;
  const p2 = document.getElementById('reg-pass2').value;
  if (!p2) { clearFieldError('reg-pass2'); return; }
  setError('reg-pass2', p1 !== p2 ? 'Паролі не збігаються' : '');
}
function togglePass(inputId, btn) {
  const inp = document.getElementById(inputId);
  inp.type = inp.type === 'password' ? 'text' : 'password';
  btn.textContent = inp.type === 'password' ? '👁' : '🙈';
}

// ════════════════════════════════════════
//  ЛОГІН
// ════════════════════════════════════════
async function doLogin() {
  const email = document.getElementById('login-email').value.trim();
  const pass  = document.getElementById('login-pass').value;
  let ok = true;
  if (!email)                    { setError('login-email', 'Введіть email'); ok = false; }
  else if (!isValidEmail(email)) { setError('login-email', 'Невірний формат email'); ok = false; }
  if (!pass)                     { setError('login-pass', 'Введіть пароль'); ok = false; }
  if (!ok) return;

  const btn = document.getElementById('btn-login');
  btn.disabled = true; btn.textContent = 'Вхід...';
  try {
    const res  = await fetch(`${API}/login`, { method:'POST', body: new URLSearchParams({ username: email, password: pass }) });
    const data = await res.json();
    if (!res.ok) { showToast(data.detail || 'Помилка входу'); return; }
    loginSuccess(data.access_token, data.user_name, data.is_admin);
  } catch { showToast('Сервер недоступний.'); }
  finally  { btn.disabled = false; btn.textContent = 'Увійти'; }
}

// ════════════════════════════════════════
//  РЕЄСТРАЦІЯ
// ════════════════════════════════════════
async function doRegister() {
  const name    = document.getElementById('reg-name').value.trim();
  const company = document.getElementById('reg-company').value.trim();
  const email   = document.getElementById('reg-email').value.trim();
  const phone   = document.getElementById('reg-phone').value.trim();
  const pass    = document.getElementById('reg-pass').value;
  const pass2   = document.getElementById('reg-pass2').value;
  const agree   = document.getElementById('reg-agree').checked;
  let ok = true;

  if (name.length < 2)               { setError('reg-name',  "Ім'я занадто коротке"); ok = false; }
  if (!email)                        { setError('reg-email', 'Введіть email'); ok = false; }
  else if (!isValidEmail(email))     { setError('reg-email', 'Невірний формат email'); ok = false; }
  if (phone && !isValidPhone(phone)) { setError('reg-phone', 'Формат: +380681234567 або 0681234567'); ok = false; }
  if (pass.length < 6)               { setError('reg-pass',  'Пароль мін. 6 символів'); ok = false; }
  if (pass !== pass2)                { setError('reg-pass2', 'Паролі не збігаються'); ok = false; }
  if (!agree)                        { showToast('Прийміть умови користування.'); ok = false; }
  if (!ok) return;

  const btn = document.getElementById('btn-register');
  btn.disabled = true; btn.textContent = 'Реєстрація...';
  try {
    const res  = await fetch(`${API}/register`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ name, company, email, phone, password: pass }),
    });
    const data = await res.json();
    if (!res.ok) { showToast(data.detail || 'Помилка реєстрації'); return; }
    loginSuccess(data.access_token, data.user_name, data.is_admin);
  } catch { showToast('Сервер недоступний.'); }
  finally  { btn.disabled = false; btn.textContent = 'Зареєструватися'; }
}

function loginSuccess(token, name, adminFlag = false) {
  isLoggedIn = true; authToken = token; userName = name; isAdmin = !!adminFlag;
  saveSession();
  updateNavForLoggedIn();
  closeAuth();
  showPage(pendingPage || 'analysis'); pendingPage = null;
  showToast(`Ласкаво просимо, ${name}! 🌱`, 'success');
  startInactivityWatcher();
}

function doLogout() {
  isLoggedIn = false; authToken = ''; userName = ''; isAdmin = false;
  clearSession();
  stopInactivityWatcher();
  updateNavForLoggedIn();
  showPage('home');
  showToast('Ви вийшли з акаунту 👋', 'info');
}

// ════════════════════════════════════════
//  FILE UPLOAD + DRAG & DROP
// ════════════════════════════════════════
function previewFile(e) { const f = e.target.files[0]; if (f) setUploadedFile(f); }

function setUploadedFile(file) {
  if (!file.type.startsWith('image/')) { showToast('Завантажте зображення (JPG, PNG, TIF).'); return; }
  uploadedFile = file;
  const url  = URL.createObjectURL(file);
  const zone = document.getElementById('upload-zone');
  zone.querySelector('.upload-icon').style.display = 'none';
  zone.querySelector('.upload-text').style.display = 'none';
  const prev = document.getElementById('preview-img');
  prev.src = url; prev.style.display = 'block';
  document.getElementById('btn-analyze').disabled = false;
  document.getElementById('result-img').style.display = 'none';
  const ph = document.getElementById('result-zone').querySelector('.result-placeholder');
  if (ph) ph.style.display = 'flex';
  document.getElementById('report-panel').innerHTML =
    "<div class=\"report-placeholder\">Результати аналізу з'являться тут після обробки знімку.</div>";
}

function initDragDrop() {
  const zone = document.getElementById('upload-zone');
  if (!zone) return;
  zone.addEventListener('dragover',  e => { e.preventDefault(); zone.classList.add('drag-over'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('drag-over'));
  zone.addEventListener('drop', e => {
    e.preventDefault(); zone.classList.remove('drag-over');
    const f = e.dataTransfer.files[0]; if (f) setUploadedFile(f);
  });
}

// ════════════════════════════════════════
//  ANALYSIS
// ════════════════════════════════════════
async function analyzeField() {
  if (!uploadedFile) return;
  const btn = document.getElementById('btn-analyze');
  btn.disabled = true; btn.innerHTML = '<div class="spinner"></div> Обробка...';
  try {
    const threshold = document.getElementById('threshold-slider').value;
    const formData  = new FormData();
    formData.append('file', uploadedFile);
    const res  = await fetch(`${API}/analyze?threshold=${threshold}`, {
      method:'POST', headers:{'Authorization':`Bearer ${authToken}`}, body: formData,
    });
    const data = await res.json();
    if (!res.ok) { showToast(data.detail || 'Помилка аналізу'); return; }

    const resultImg = document.getElementById('result-img');
    resultImg.src = `data:image/png;base64,${data.mask_base64}`;
    resultImg.style.display = 'block';
    const ph = document.getElementById('result-zone').querySelector('.result-placeholder');
    if (ph) ph.style.display = 'none';

    const panel = document.getElementById('report-panel');
    if (data.detections.length) {
      panel.innerHTML = `
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:1rem;">
          <strong style="color:var(--cream)"> Результат аналізу</strong>
          <span class="success-badge">Знайдено: ${data.detections.length}</span>
        </div>`;
      data.detections.forEach(d => {
        panel.innerHTML += `
          <div class="report-item">
            <div class="report-item-title">${d.label_ua}</div>
            <div class="report-item-stats">
              <div class="stat">Площа: <span class="val">${d.area_pct}%</span></div>
              <div class="stat">Впевненість: <span class="val">${Math.round(d.confidence*100)}%</span></div>
            </div>
            <div class="report-item-advice">💡 ${d.advice}</div>
          </div>`;
      });
      showToast(`Аналіз завершено. Аномалій: ${data.detections.length}`, 'info');
    } else {
      panel.innerHTML = `
        <div style="text-align:center;padding:1rem;">
          <div style="font-size:2rem;margin-bottom:.5rem"></div>
          <div style="color:var(--cream);font-weight:700;margin-bottom:.5rem">Аномалій не виявлено</div>
          <div style="color:var(--text3);font-size:.85rem">Поле виглядає здоровим.</div>
        </div>`;
      showToast('Аномалій не виявлено ', 'success');
    }
  } catch { showToast("Помилка з'єднання з сервером."); }
  finally  { btn.disabled = false; btn.innerHTML = ' Аналізувати поле'; }
}

// ════════════════════════════════════════
//  HISTORY
// ════════════════════════════════════════
// ════════════════════════════════════════
//  HISTORY — замінити функцію loadHistory в script.js
// ════════════════════════════════════════
async function loadHistory() {
  const el = document.getElementById('history-content');
  el.innerHTML = '<div style="color:var(--text3);padding:2rem;text-align:center">Завантаження...</div>';
  try {
    const res  = await fetch(`${API}/history`, { headers: { 'Authorization': `Bearer ${authToken}` } });
    const data = await res.json();
    if (!data.length) {
      el.innerHTML = `
        <div class="history-empty">
          <div class="icon">📂</div>
          <p style="color:var(--text2);margin-bottom:.5rem;">Аналізи ще не виконувались</p>
          <p style="font-size:.85rem;">Після першого аналізу поля тут з'являться збережені результати.</p>
        </div>`;
      return;
    }
    el.innerHTML = '';
    data.forEach(h => {
      const detTags = (h.detections || []).map(d => `
        <div class="hist-det-tag">
          <span class="hist-det-name">${d.label_ua || d.class_name || d.label || '—'}</span>
          <span class="hist-det-conf">${Math.round((d.confidence || 0) * 100)}%</span>
        </div>
      `).join('');
      const noAnom = !h.detections || h.detections.length === 0;
      el.innerHTML += `
        <div class="history-item history-item-rich">
          <!-- Фото з S3 -->
          <div class="history-thumb-img">
            ${h.image_url
              ? `<img src="${h.image_url}" alt="поле" onerror="this.parentElement.innerHTML='🛰️'">`
              : '<span>🛰️</span>'
            }
          </div>

          <!-- Інфо -->
          <div class="history-info" style="flex:1;min-width:0;">
            <div style="display:flex;align-items:center;gap:.75rem;margin-bottom:.4rem;flex-wrap:wrap;">
              <h3 style="color:var(--cream2);font-size:.95rem;">${h.filename}</h3>
              <span class="history-tag" style="margin-left:0;">Аномалій: ${h.anomalies_count}</span>
            </div>
            <p style="color:var(--text3);font-size:.8rem;margin-bottom:.6rem;">
              📅 ${h.date} &nbsp;·&nbsp; 🎚️ Поріг: ${h.threshold}
            </p>
            ${noAnom
              ? '<p style="font-size:.82rem;color:var(--green2)">✅ Аномалій не виявлено</p>'
              : `<div class="hist-det-list">${detTags}</div>`
            }
          </div>
        </div>`;
    });
  } catch {
    el.innerHTML = '<div style="color:var(--text3);padding:2rem;text-align:center">Помилка завантаження.</div>';
  }
}

// ════════════════════════════════════════
//  АДМІН
// ════════════════════════════════════════
let adminTab = 'users';

function _showAdminNav() {
  let btn = document.getElementById('btn-admin-panel');
  if (isAdmin && !btn) {
    btn = document.createElement('button');
    btn.className = 'nav-btn';
    btn.id = 'btn-admin-panel';
    btn.textContent = '🛡️ Адмін';
    btn.onclick = () => requireAuth('admin');
    const logoutBtn = document.getElementById('btn-logout');
    document.querySelector('.nav-links').insertBefore(btn, logoutBtn || document.getElementById('btn-auth'));
  }
  if (!isAdmin && btn) btn.remove();
}

function switchAdminTab(tab) {
  adminTab = tab;
  document.getElementById('atab-users').classList.toggle('active', tab === 'users');
  document.getElementById('atab-analyses').classList.toggle('active', tab === 'analyses');
  document.getElementById('admin-users-section').style.display    = tab === 'users'    ? 'block' : 'none';
  document.getElementById('admin-analyses-section').style.display = tab === 'analyses' ? 'block' : 'none';
}

async function loadAdminData() { loadAdminUsers(); loadAdminAnalyses(); }

async function loadAdminUsers() {
  const el = document.getElementById('admin-users-list');
  el.innerHTML = '<p style="color:var(--text3)">Завантаження...</p>';
  try {
    const res  = await fetch(`${API}/admin/users`, { headers:{Authorization:`Bearer ${authToken}`} });
    const data = await res.json();
    if (!res.ok) { el.innerHTML = `<p style="color:#e74c3c">${data.detail}</p>`; return; }
    el.innerHTML = `
      <table class="admin-table">
        <thead><tr>
          <th>ID</th><th>Ім'я</th><th>Email</th><th>Компанія</th>
          <th>Аналізів</th><th>Останній вхід</th><th>Статус</th><th>Дії</th>
        </tr></thead>
        <tbody>
          ${data.map(u => `
            <tr id="user-row-${u.id}" class="${!u.is_active ? 'row-inactive' : ''}">
              <td>${u.id}</td>
              <td>${u.name}${u.is_admin ? ' 🛡️' : ''}</td>
              <td>${u.email}</td>
              <td>${u.company || '—'}</td>
              <td>${u.analyses_count}</td>
              <td>${u.last_login}</td>
              <td><span class="status-badge ${u.is_active ? 'active' : 'inactive'}">${u.is_active ? 'Активний' : 'Деактивовано'}</span></td>
              <td class="action-cell">
                <button class="adm-btn toggle" onclick="adminToggleUser(${u.id})">${u.is_active ? 'Деактивувати' : 'Активувати'}</button>
                <button class="adm-btn del"    onclick="adminDeleteUser(${u.id}, '${u.email}')">Видалити</button>
              </td>
            </tr>`).join('')}
        </tbody>
      </table>`;
  } catch { el.innerHTML = '<p style="color:#e74c3c">Помилка завантаження</p>'; }
}

async function loadAdminAnalyses() {
  const el = document.getElementById('admin-analyses-list');
  el.innerHTML = '<p style="color:var(--text3)">Завантаження...</p>';
  try {
    const res  = await fetch(`${API}/admin/analyses`, { headers:{Authorization:`Bearer ${authToken}`} });
    const data = await res.json();
    if (!res.ok) { el.innerHTML = `<p style="color:#e74c3c">${data.detail}</p>`; return; }
    el.innerHTML = `
      <table class="admin-table">
        <thead><tr>
          <th>ID</th><th>Файл</th><th>Користувач</th><th>Дата</th>
          <th>Аномалій</th><th>Поріг</th><th>Фото</th><th>Дії</th>
        </tr></thead>
        <tbody>
          ${data.map(a => `
            <tr id="an-row-${a.id}">
              <td>${a.id}</td>
              <td>${a.filename}</td>
              <td>${a.user_name}<br><small>${a.user_email}</small></td>
              <td>${a.date}</td>
              <td>${a.anomalies_count}</td>
              <td>${a.threshold}</td>
              <td>${a.image_url ? `<a href="${a.image_url}" target="_blank">🖼️</a>` : '—'}</td>
              <td><button class="adm-btn del" onclick="adminDeleteAnalysis(${a.id})">Видалити</button></td>
            </tr>`).join('')}
        </tbody>
      </table>`;
  } catch { el.innerHTML = '<p style="color:#e74c3c">Помилка завантаження</p>'; }
}

async function adminToggleUser(id) {
  const res  = await fetch(`${API}/admin/users/${id}/toggle-active`, { method:'PATCH', headers:{Authorization:`Bearer ${authToken}`} });
  const data = await res.json();
  if (!res.ok) { showToast(data.detail); return; }
  showToast(data.is_active ? 'Активовано ✅' : 'Деактивовано 🚫', 'info');
  loadAdminUsers();
}

async function adminDeleteUser(id, email) {
  if (!confirm(`Видалити користувача ${email} і всі його аналізи?`)) return;
  const res  = await fetch(`${API}/admin/users/${id}`, { method:'DELETE', headers:{Authorization:`Bearer ${authToken}`} });
  const data = await res.json();
  if (!res.ok) { showToast(data.detail); return; }
  showToast('Користувача видалено', 'success');
  loadAdminUsers(); loadAdminAnalyses();
}

async function adminDeleteAnalysis(id) {
  if (!confirm('Видалити цей аналіз?')) return;
  const res  = await fetch(`${API}/admin/analyses/${id}`, { method:'DELETE', headers:{Authorization:`Bearer ${authToken}`} });
  const data = await res.json();
  if (!res.ok) { showToast(data.detail); return; }
  showToast('Аналіз видалено', 'success');
  loadAdminAnalyses();
}