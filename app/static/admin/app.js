/* Panel admin Tanya Kampus. Tanpa build step, tanpa dependensi.
   Semua data dari server dirender lewat textContent / node DOM (bukan innerHTML). */
(() => {
  'use strict';

  // ---------- util ----------
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

  function h(tag, attrs, ...children) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === 'class') el.className = v;
      else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
      else if (k === 'value') el.value = v;
      else if (v === true) el.setAttribute(k, '');
      else el.setAttribute(k, v);
    }
    for (const c of children.flat()) {
      if (c === null || c === undefined || c === false) continue;
      el.append(typeof c === 'object' ? c : String(c));
    }
    return el;
  }

  const memory = {};
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch { return memory[k] ?? null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch { memory[k] = v; } },
    del(k) { try { localStorage.removeItem(k); } catch { delete memory[k]; } },
  };

  let token = store.get('tk_token');
  let meta = null;
  let docsCache = [];

  function toast(msg, isErr = false) {
    const t = h('div', { class: 'toast' + (isErr ? ' err' : ''), role: 'status' }, msg);
    $('#toasts').append(t);
    setTimeout(() => t.remove(), isErr ? 6000 : 3200);
  }

  function fmtDetail(d) {
    if (typeof d === 'string') return d;
    if (Array.isArray(d)) return d.map((e) => (e.msg || JSON.stringify(e)).replace(/^Value error, /, '')).join('; ');
    return JSON.stringify(d);
  }

  async function api(path, { method = 'GET', json, form, raw = false } = {}) {
    const headers = {};
    if (token) headers.Authorization = 'Bearer ' + token;
    let body;
    if (json !== undefined) { headers['Content-Type'] = 'application/json'; body = JSON.stringify(json); }
    else if (form) body = form;
    const res = await fetch('/api' + path, { method, headers, body });
    if (res.status === 401 && token && !path.startsWith('/auth/login')) {
      logout();
      throw new Error('Sesi berakhir. Silakan masuk lagi.');
    }
    if (!res.ok) {
      let detail = res.statusText || 'Terjadi kesalahan';
      let data = null;
      try { data = await res.json(); detail = fmtDetail(data.detail ?? data); } catch { /* bukan JSON */ }
      const err = new Error(detail);
      err.status = res.status;
      err.data = data;
      throw err;
    }
    if (res.status === 204) return null;
    return raw ? res : res.json();
  }

  function parseDate(s) {
    if (!s) return null;
    const d = new Date(s.includes('T') ? s : s.replace(' ', 'T') + 'Z');
    return isNaN(d) ? null : d;
  }
  function fmtDateTime(s) {
    const d = parseDate(s);
    return d ? d.toLocaleString('id-ID', { dateStyle: 'medium', timeStyle: 'short' }) : '-';
  }

  const SOURCE_LABEL = { file: 'File', url: 'URL', manual: 'Manual' };

  function statusBadge(doc) {
    if (doc.status === 'error') return h('span', { class: 'badge error', title: doc.error || '' }, 'Error');
    if (doc.status === 'draft') return h('span', { class: 'badge draft' }, 'Draft');
    if (doc.dirty) return h('span', { class: 'badge dirty', title: 'Isi atau judul berubah sejak index terakhir' }, 'Perlu index ulang');
    return h('span', { class: 'badge indexed' }, 'Terindeks');
  }

  async function busy(btn, busyText, fn) {
    const label = btn.textContent;
    btn.disabled = true;
    btn.textContent = busyText;
    try { return await fn(); }
    finally { btn.disabled = false; btn.textContent = label; }
  }

  // ---------- login / sesi ----------
  function showLogin() {
    $('#view-app').hidden = true;
    $('#view-login').hidden = false;
    $('#login-form [name=username]').focus();
  }

  function logout() {
    token = null;
    store.del('tk_token');
    showLogin();
  }

  $('#login-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const f = e.target;
    const err = $('#login-error');
    err.hidden = true;
    const btn = $('button[type=submit]', f);
    btn.disabled = true;
    try {
      const data = await api('/auth/login', { method: 'POST', json: { username: f.username.value.trim(), password: f.password.value } });
      token = data.access_token;
      store.set('tk_token', token);
      f.password.value = '';
      await enterApp(data.username);
    } catch (ex) {
      err.textContent = ex.message;
      err.hidden = false;
    } finally { btn.disabled = false; }
  });

  $('#btn-logout').addEventListener('click', logout);
  $('#btn-logout-side').addEventListener('click', logout);

  // menu akun di pojok kanan atas
  const userBtn = $('#user-btn');
  const userPop = $('#user-pop');
  function setUserMenu(open) { userPop.hidden = !open; userBtn.setAttribute('aria-expanded', String(open)); }
  userBtn.addEventListener('click', () => setUserMenu(userPop.hidden));
  userPop.addEventListener('click', () => setUserMenu(false));
  document.addEventListener('click', (e) => { if (!e.target.closest('.user-menu')) setUserMenu(false); });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !userPop.hidden) { setUserMenu(false); userBtn.focus(); } });

  async function enterApp(username) {
    $('#view-login').hidden = true;
    $('#view-app').hidden = false;
    $('#whoami').textContent = username || '';
    $('#avatar').textContent = (username || 'A').trim().charAt(0) || 'A';
    meta = await api('/meta');
    renderMeta();
    await refreshDocs();
  }

  function renderMeta() {
    $('#category-list').replaceChildren(...meta.categories.map((c) => h('option', { value: c })));
    const sel = $('#ask-form [name=category]');
    const cur = sel.value;
    sel.replaceChildren(h('option', { value: '' }, 'Semua kategori'), ...meta.categories.map((c) => h('option', { value: c }, c)));
    sel.value = cur;
    const b = $('#banners');
    b.replaceChildren(...meta.warnings.map((w) => h('div', { class: 'banner', role: 'alert' }, w)));
    if (!meta.telegram_upload_enabled) { /* fitur opsional, tidak perlu banner */ }
  }

  // ---------- tab ----------
  const PAGES = {
    docs: ['Ikhtisar', 'Kelola knowledge yang dipakai bot untuk menjawab.'],
    ask: ['Tes Tanya', 'Coba pertanyaan dan lihat skor tiap chunk sebelum dipakai mahasiswa.'],
    logs: ['Log', 'Pertanyaan yang masuk dari mahasiswa beserta hasilnya.'],
  };

  function selectTab(name) {
    $$('.tab').forEach((t) => {
      t.classList.toggle('active', t.dataset.tab === name);
      t.setAttribute('aria-selected', String(t.dataset.tab === name));
    });
    $('#page-title').textContent = PAGES[name][0];
    $('#page-sub').textContent = PAGES[name][1];
    $$('.panel').forEach((p) => { p.hidden = p.id !== 'tab-' + name; });
    if (name === 'docs') refreshDocs();
    if (name === 'logs') refreshLogs();
  }
  $$('.tab').forEach((t) => t.addEventListener('click', () => selectTab(t.dataset.tab)));

  // ---------- dokumen ----------
  async function refreshDocs() {
    try {
      const [docs, stats] = await Promise.all([api('/documents'), api('/stats')]);
      docsCache = docs;
      renderStats(stats);
      applyDocFilter();
    } catch (ex) { toast(ex.message, true); }
  }

  // ikon garis sederhana untuk kartu knowledge (path SVG 24x24)
  const SVG_NS = 'http://www.w3.org/2000/svg';
  const ICON_PATHS = {
    doc: 'M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8zM14 3v5h5M9 13h6M9 17h4',
    check: 'M20 6 9 17l-5-5',
    clock: 'M12 7v5l3 2M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0z',
  };
  function svg(tag, attrs, ...children) {
    const el = document.createElementNS(SVG_NS, tag);
    for (const [k, v] of Object.entries(attrs || {})) el.setAttribute(k, v);
    el.append(...children);
    return el;
  }
  const icon = (name) => svg('svg', { viewBox: '0 0 24 24', 'aria-hidden': 'true' }, svg('path', { d: ICON_PATHS[name] }));
  const fmtNum = (n) => Number(n || 0).toLocaleString('id-ID');

  // 7 tanggal terakhir (UTC, sama dengan date() di SQLite), lengkap walau ada hari tanpa pertanyaan
  function lastDays(byDay) {
    const map = new Map((byDay || []).map((d) => [d.day, d]));
    const out = [];
    for (let i = 6; i >= 0; i -= 1) {
      const key = new Date(Date.now() - i * 864e5).toISOString().slice(0, 10);
      const d = map.get(key);
      out.push({ day: key, total: d ? d.total : 0, not_found: d ? d.not_found || 0 : 0 });
    }
    return out;
  }

  function renderChart(days) {
    const W = 300, H = 92, max = Math.max(1, ...days.map((d) => d.total));
    const x = (i) => (i / (days.length - 1)) * W;
    const y = (v) => H - 6 - (v / max) * (H - 16);
    const pts = (key) => days.map((d, i) => `${x(i).toFixed(1)},${y(d[key]).toFixed(1)}`).join(' ');
    const chart = svg('svg', { viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: 'none', role: 'img',
      'aria-label': 'Grafik pertanyaan 7 hari terakhir: ' + days.map((d) => d.total).join(', ') },
      svg('g', { class: 'grid' }, ...[0.25, 0.5, 0.75].map((f) => svg('line', { x1: 0, x2: W, y1: H * f, y2: H * f }))),
      svg('polygon', { class: 'area', points: `0,${H} ${pts('total')} ${W},${H}` }),
      svg('polyline', { class: 'nf', points: pts('not_found') }),
      svg('polyline', { class: 'line', points: pts('total') }));
    const last = days[days.length - 1];
    const pos = `left:100%;top:${(y(last.total) / H) * 100}%`;
    const fmtDay = (key) => new Date(key + 'T00:00:00Z').toLocaleDateString('id-ID', { weekday: 'short', timeZone: 'UTC' });
    return h('div', {},
      h('div', { class: 'chart' }, chart,
        h('span', { class: 'dot', style: pos }),
        h('span', { class: 'bubble', style: pos }, `${fmtNum(last.total)} hari ini`)),
      h('div', { class: 'days' }, days.map((d, i) => h('span', { class: i === days.length - 1 ? 'today' : '' }, fmtDay(d.day)))));
  }

  function renderStats(s) {
    const days = lastDays(s.by_day);
    const week = days.reduce((a, d) => a + d.total, 0);
    const rate = s.queries ? Math.round((s.answered / s.queries) * 100) : 0;
    $('#summary').replaceChildren(
      h('div', { class: 'summary-top' },
        h('div', {}, h('div', { class: 'big' }, fmtNum(s.queries)), h('div', { class: 'l' }, 'Pertanyaan masuk')),
        h('div', { class: 'mini-stats' },
          h('span', {}, h('b', {}, `${rate}%`), ' terjawab'),
          h('span', {}, h('b', {}, fmtNum(s.not_found)), ' tidak ditemukan'),
          h('span', {}, h('b', {}, fmtNum(s.feedback_up)), ' membantu, ', h('b', {}, fmtNum(s.feedback_down)), ' kurang tepat'))),
      h('div', { class: 'legend' }, h('span', {}, h('i', {}), `${fmtNum(week)} pertanyaan minggu ini`), h('span', {}, h('i', { class: 'nf' }), 'tidak ditemukan')),
      renderChart(days));

    const pct = s.documents ? Math.round((s.documents_indexed / s.documents) * 100) : 0;
    const asset = (cls, value, label, sub, ic, delta, deltaCls) => h('div', { class: 'asset ' + cls },
      h('div', { class: 'big' }, fmtNum(value)), h('div', { class: 'l' }, label), h('div', { class: 's' }, sub),
      h('div', { class: 'asset-foot' }, h('span', { class: 'asset-icon' }, icon(ic)), h('span', { class: 'delta ' + (deltaCls || '') }, delta)));
    $('#stats').replaceChildren(
      asset('c1', s.documents, 'Dokumen', `${fmtNum(s.chunks)} chunk`, 'doc', ''),
      asset('c2', s.documents_indexed, 'Terindeks', 'siap dijawab bot', 'check', `${pct}%`, 'good'),
      asset('c3', s.documents_need_index, 'Perlu di-index', 'draft atau berubah', 'clock',
        s.documents_need_index > 0 ? 'cek tabel' : 'beres', s.documents_need_index > 0 ? 'warn' : 'good'),
    );
  }

  function applyDocFilter() {
    const q = $('#doc-search').value.trim().toLowerCase();
    const mode = $('#doc-filter').value;
    const list = docsCache.filter((d) => {
      if (mode === 'need' && d.status === 'indexed' && !d.dirty) return false;
      if (mode === 'indexed' && !(d.status === 'indexed' && !d.dirty)) return false;
      if (!q) return true;
      return [d.title, d.source_name, d.category, d.source_url].some((v) => (v || '').toLowerCase().includes(q));
    });
    $('#docs-empty').textContent = docsCache.length && !list.length
      ? 'Tidak ada dokumen yang cocok dengan pencarian.'
      : 'Belum ada dokumen. Tambahkan lewat Upload file, Dari URL, atau Tulis manual.';
    $('#docs-count').textContent = list.length === docsCache.length ? list.length : `${list.length} dari ${docsCache.length}`;
    renderDocs(list);
  }
  $('#doc-search').addEventListener('input', applyDocFilter);
  $('#doc-filter').addEventListener('change', applyDocFilter);

  function renderDocs(docs) {
    $('#docs-empty').hidden = docs.length > 0;
    $('#docs-body').replaceChildren(...docs.map((d) => {
      const tr = h('tr', { class: 'clickable', tabindex: '0' },
        h('td', {},
          h('div', { class: 'title' }, d.title,
            d.note && h('span', { class: 'tag-mini', title: d.note }, /OCR/.test(d.note) ? 'OCR' : 'Cek konversi'),
            d.downloadable && h('span', { class: 'tag-mini info', title: 'Bot boleh mengirim file asli ke mahasiswa' }, 'Unduh')),
          d.effective_date && h('div', { class: 'sub' }, 'Berlaku ' + d.effective_date)),
        h('td', { 'data-label': 'Kategori' }, d.category),
        h('td', { 'data-label': 'Sumber' }, SOURCE_LABEL[d.source_type] || d.source_type, d.source_name && h('div', { class: 'sub' }, d.source_name)),
        h('td', { 'data-label': 'Status' }, statusBadge(d)),
        h('td', { class: 'num', 'data-label': 'Chunk' }, d.chunk_count),
        h('td', { 'data-label': 'Diperbarui' }, fmtDateTime(d.updated_at)),
        h('td', { class: 'actions' },
          h('button', { class: 'btn small', onclick: (e) => { e.stopPropagation(); indexFromList(d, e.currentTarget); } },
            d.status === 'indexed' && !d.dirty ? 'Index ulang' : 'Index')),
      );
      tr.addEventListener('click', () => openEdit(d.id));
      tr.addEventListener('keydown', (e) => { if (e.key === 'Enter') openEdit(d.id); });
      return tr;
    }));
  }

  async function indexFromList(doc, btn) {
    await busy(btn, 'Memproses...', async () => {
      try {
        const r = await api(`/documents/${doc.id}/index`, { method: 'POST' });
        toast(`"${r.title}" terindeks: ${r.chunk_count} chunk.`);
      } catch (ex) { toast(ex.message, true); }
    });
    refreshDocs();
  }

  $('#btn-reindex').addEventListener('click', async (e) => {
    if (!confirm('Hitung ulang embedding semua dokumen? Untuk dokumen banyak ini bisa memakan waktu.')) return;
    await busy(e.currentTarget, 'Memproses...', async () => {
      try {
        const r = await api('/reindex', { method: 'POST' });
        toast(`Re-index selesai: ${r.ok}/${r.total} berhasil` + (r.failed.length ? `, ${r.failed.length} gagal.` : '.'), r.failed.length > 0);
      } catch (ex) { toast(ex.message, true); }
    });
    refreshDocs();
  });

  // ---------- dialog umum ----------
  $$('dialog').forEach((dlg) => {
    dlg.addEventListener('click', (e) => { if (e.target.closest('[data-close]')) dlg.close(); });
    dlg.addEventListener('mousedown', (e) => { if (e.target === dlg) dlg.close(); });
  });
  function showError(sel, msg) {
    const el = $(sel);
    el.textContent = msg || '';
    el.hidden = !msg;
  }

  // ---------- tambah dokumen ----------
  let addMode = 'file';
  const ADD_TITLES = { file: 'Upload file', url: 'Tambah dari URL', manual: 'Tulis manual' };

  $$('[data-add]').forEach((b) => b.addEventListener('click', () => openAdd(b.dataset.add)));

  function openAdd(mode) {
    addMode = mode;
    const form = $('#add-form');
    form.reset();
    form.category.value = 'akademik';
    form.title.disabled = false;
    form.title.placeholder = '';
    showError('#add-error', '');
    $('#add-results').replaceChildren();
    $('#add-results').hidden = true;
    $('#add-title').textContent = ADD_TITLES[mode];
    $('#add-downloadable-wrap').hidden = mode !== 'file';
    $('#add-submit').textContent = 'Buat';
    $('#dlg-add [data-close]').textContent = 'Batal';
    const src = $('#add-source');
    if (mode === 'file') {
      const ocr = meta && meta.ocr;
      const ocrHint = ocr && ocr.ready
        ? 'PDF scan dan gambar (PNG/JPG/TIFF) dibaca dengan OCR; hasilnya perlu ditinjau.'
        : 'OCR belum aktif, jadi PDF scan dan gambar akan ditolak. ' + (ocr ? ocr.message : '');
      const input = h('input', { type: 'file', name: 'file', required: true, multiple: true,
        accept: '.pdf,.docx,.pptx,.xlsx,.html,.htm,.csv,.md,.markdown,.txt,.png,.jpg,.jpeg,.tif,.tiff,.bmp' });
      input.addEventListener('change', () => {
        const many = input.files.length > 1;
        form.title.disabled = many;
        form.title.placeholder = many ? 'Judul diambil dari nama tiap file' : '';
        if (many) form.title.value = '';
      });
      src.replaceChildren(h('label', {}, 'File (boleh pilih beberapa)', input,
        h('span', { class: 'hint' }, 'PDF, DOCX, PPTX, XLSX, HTML, CSV, MD, TXT, atau gambar. ' + ocrHint)));
    } else if (mode === 'url') {
      src.replaceChildren(h('label', {}, 'URL halaman',
        h('input', { type: 'url', name: 'url', required: true, placeholder: 'https://...' }),
        h('span', { class: 'hint' }, 'Hanya halaman publik. Halaman yang dirender JavaScript belum didukung.')));
    } else {
      src.replaceChildren(
        h('label', {}, 'Isi (markdown)', h('textarea', { name: 'markdown', rows: 10, required: true, class: 'mono', spellcheck: 'false', placeholder: '# Judul\n\n## Bagian\n\nIsi...' })),
        h('label', {}, 'URL sumber (opsional)', h('input', { type: 'url', name: 'source_url' })));
    }
    form.title.required = mode === 'manual';
    $('#dlg-add').showModal();
  }

  function resultRow(name) {
    const status = h('span', {}, 'menunggu...');
    const li = h('li', {}, h('span', { class: 'name' }, name), status);
    $('#add-results').append(li);
    return (kind, text) => { status.className = kind; status.textContent = text; };
  }

  $('#add-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const f = e.target;
    showError('#add-error', '');
    const btn = $('#add-submit');
    const auto = f.autoindex.checked;
    const common = { category: f.category.value, effective_date: f.effective_date.value || null };
    const titleInput = f.title.value.trim() || null;

    // satu item = satu dokumen yang akan dibuat
    let items;
    if (addMode === 'file') items = [...f.file.files].map((file) => ({ label: file.name, file }));
    else items = [{ label: addMode === 'url' ? f.url.value.trim() : (titleInput || 'Teks manual') }];
    const multi = items.length > 1;
    $('#add-results').replaceChildren();
    $('#add-results').hidden = !multi;

    async function createOne(item) {
      if (addMode === 'file') {
        const fd = new FormData();
        fd.append('file', item.file);
        if (!multi && titleInput) fd.append('title', titleInput);
        fd.append('category', common.category);
        if (common.effective_date) fd.append('effective_date', common.effective_date);
        fd.append('downloadable', f.downloadable.checked ? 'true' : 'false');
        return api('/documents/upload', { method: 'POST', form: fd });
      }
      if (addMode === 'url') return api('/documents/url', { method: 'POST', json: { ...common, title: titleInput, url: f.url.value.trim() } });
      return api('/documents/manual', { method: 'POST', json: { ...common, title: titleInput, markdown: f.markdown.value, source_url: f.source_url.value || null } });
    }

    btn.disabled = true;
    btn.textContent = 'Memproses...';
    const created = [];
    let failed = 0;
    try {
      for (const item of items) {
        const mark = multi ? resultRow(item.label) : () => {};
        try {
          mark('', 'mengonversi...');
          let doc = await createOne(item);
          if (auto) { mark('', 'meng-index...'); doc = await api(`/documents/${doc.id}/index`, { method: 'POST' }); }
          created.push(doc);
          mark('ok', (auto ? `terindeks, ${doc.chunk_count} chunk` : 'draft dibuat') + (doc.note ? ' (cek catatan konversi)' : ''));
        } catch (ex) {
          failed += 1;
          if (!multi) throw ex;
          mark(ex.status === 409 ? 'skip' : 'bad', (ex.status === 409 ? 'dilewati, ' : 'gagal: ') + ex.message);
        }
      }
      await refreshDocs();
      if (multi) {
        $('#dlg-add [data-close]').textContent = 'Tutup';
        toast(`${created.length} dokumen dibuat` + (failed ? `, ${failed} gagal atau dilewati.` : '.'), failed > 0);
      } else {
        $('#dlg-add').close();
        if (auto) toast(`Terindeks: ${created[0].chunk_count} chunk.`);
        else { toast('Draft dibuat. Periksa isinya, lalu Index.'); openEdit(created[0].id); }
      }
    } catch (ex) {
      showError('#add-error', ex.message);
    } finally {
      btn.disabled = false;
      btn.textContent = 'Buat';
    }
  });

  // ---------- edit dokumen ----------
  let editing = null;

  async function openEdit(id) {
    try {
      editing = await api('/documents/' + id);
    } catch (ex) { toast(ex.message, true); return; }
    fillEdit();
    showError('#edit-error', '');
    $('#dlg-edit').showModal();
  }

  function fillEdit() {
    const f = $('#edit-form');
    f.title.value = editing.title;
    f.category.value = editing.category;
    f.effective_date.value = editing.effective_date || '';
    f.source_url.value = editing.source_url || '';
    f.markdown.value = editing.markdown;
    $('#edit-status').replaceChildren(statusBadge(editing), editing.chunk_count ? h('span', { class: 'muted' }, ` ${editing.chunk_count} chunk`) : '');
    $('#edit-download').hidden = !editing.has_original;
    const note = $('#edit-note');
    note.textContent = editing.note || '';
    note.hidden = !editing.note;
    f.downloadable.checked = !!editing.downloadable;
    $('#edit-downloadable-wrap').hidden = !editing.has_original;
  }

  function editPayload() {
    const f = $('#edit-form');
    return {
      title: f.title.value.trim(),
      category: f.category.value,
      effective_date: f.effective_date.value || null,
      source_url: f.source_url.value.trim(),
      markdown: f.markdown.value,
      downloadable: editing.has_original ? f.downloadable.checked : undefined,
    };
  }

  async function saveEdit(thenIndex, btn) {
    showError('#edit-error', '');
    await busy(btn, thenIndex ? 'Meng-index...' : 'Menyimpan...', async () => {
      try {
        editing = await api('/documents/' + editing.id, { method: 'PUT', json: editPayload() });
        if (thenIndex) editing = await api(`/documents/${editing.id}/index`, { method: 'POST' });
        fillEdit();
        toast(thenIndex ? `Tersimpan dan terindeks: ${editing.chunk_count} chunk.` : 'Tersimpan.');
        refreshDocs();
      } catch (ex) { showError('#edit-error', ex.message); }
    });
  }

  $('#edit-save').addEventListener('click', (e) => saveEdit(false, e.currentTarget));
  $('#edit-save-index').addEventListener('click', (e) => saveEdit(true, e.currentTarget));

  $('#edit-delete').addEventListener('click', async () => {
    if (!confirm(`Hapus "${editing.title}" beserta seluruh chunk-nya? Tindakan ini tidak bisa dibatalkan.`)) return;
    try {
      await api('/documents/' + editing.id, { method: 'DELETE' });
      $('#dlg-edit').close();
      toast('Dokumen dihapus.');
      refreshDocs();
    } catch (ex) { showError('#edit-error', ex.message); }
  });

  $('#edit-download').addEventListener('click', async () => {
    try {
      const res = await api(`/documents/${editing.id}/original`, { raw: true });
      const blob = await res.blob();
      const a = h('a', { href: URL.createObjectURL(blob), download: editing.source_name || 'dokumen' });
      document.body.append(a);
      a.click();
      setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
    } catch (ex) { showError('#edit-error', ex.message); }
  });

  $('#edit-replace').addEventListener('change', async (e) => {
    const file = e.target.files[0];
    e.target.value = '';
    if (!file) return;
    if (!confirm('Ganti isi dokumen dengan file ini? Markdown saat ini akan ditimpa (chunk lama tetap aktif sampai di-index ulang).')) return;
    try {
      const fd = new FormData();
      fd.append('file', file);
      editing = await api(`/documents/${editing.id}/replace`, { method: 'POST', form: fd });
      fillEdit();
      toast('File diganti. Periksa hasil konversi, lalu Simpan & Index.');
      refreshDocs();
    } catch (ex) { showError('#edit-error', ex.message); }
  });

  $('#edit-chunks').addEventListener('click', async () => {
    try {
      const chunks = await api(`/documents/${editing.id}/chunks`);
      $('#chunks-title').textContent = `Chunk: ${editing.title} (${chunks.length})`;
      $('#chunks-list').replaceChildren(...(chunks.length ? chunks.map((c) =>
        h('div', { class: 'chunk' },
          h('div', { class: 'path' }, `#${c.chunk_index + 1}  ${c.heading_path}`),
          h('pre', {}, c.content),
          h('div', { class: 'info' }, `${c.content.length} karakter · ${c.embedding_model || 'tanpa embedding'}`)))
        : [h('p', { class: 'empty' }, 'Belum ada chunk. Index dokumen ini terlebih dulu.')]));
      $('#dlg-chunks').showModal();
    } catch (ex) { showError('#edit-error', ex.message); }
  });

  // ---------- tes tanya ----------
  const STATUS_LABEL = { answered: 'Terjawab', not_found: 'Tidak ditemukan', error: 'Error' };

  $('#ask-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const f = e.target;
    const btn = $('button[type=submit]', f);
    const out = $('#ask-result');
    out.replaceChildren(h('p', { class: 'muted' }, 'Mencari jawaban...'));
    await busy(btn, 'Mencari...', async () => {
      try {
        const r = await api('/admin/ask', { method: 'POST', json: { question: f.question.value, category: f.category.value || null } });
        out.replaceChildren(renderAnswer(r));
      } catch (ex) { out.replaceChildren(h('p', { class: 'error' }, ex.message)); }
    });
  });

  function renderAnswer(r) {
    const thr = meta.score_threshold;
    return h('div', { class: 'card result' },
      h('div', { class: 'meta-line' },
        h('span', { class: 'badge ' + r.status }, STATUS_LABEL[r.status] || r.status),
        r.top_score !== null && h('span', {}, `Skor tertinggi ${r.top_score.toFixed(3)} (ambang ${thr})`),
        r.cached && h('span', {}, 'dari cache')),
      h('div', { class: 'answer' }, r.answer),
      r.sources.length > 0 && h('div', {}, h('h3', {}, 'Sumber'),
        h('ul', { class: 'sources' }, r.sources.map((s) =>
          h('li', {}, `[${s.n}] `, s.url ? h('a', { href: s.url, target: '_blank', rel: 'noopener noreferrer' }, s.title) : s.title,
            s.heading ? ` › ${s.heading.split(' > ').slice(1).join(' › ') || s.heading}` : '',
            s.effective_date ? ` (berlaku ${s.effective_date})` : '')))),
      r.hits && r.hits.length > 0 && h('div', {}, h('h3', {}, 'Chunk yang ditemukan (debug)'),
        h('div', { class: 'table-wrap' }, h('table', {},
          h('thead', {}, h('tr', {}, ['#', 'Bagian', 'Semantik', 'Keyword', 'Skor'].map((t) => h('th', {}, t)))),
          h('tbody', {}, r.hits.map((x, i) => h('tr', {},
            h('td', {}, i + 1),
            h('td', {}, h('div', { class: 'title' }, x.title), h('div', { class: 'sub' }, x.heading), h('div', { class: 'snippet' }, x.snippet)),
            h('td', {}, scoreCell(x.semantic)), h('td', {}, scoreCell(x.lexical)),
            h('td', {}, scoreCell(x.score, x.score >= thr))))))))
    );
  }

  function scoreCell(v, strong) {
    return h('div', { class: 'score-cell' }, h('div', { class: 'bar', style: 'width:70px' }, h('i', { style: `width:${Math.max(0, Math.min(1, v)) * 100}%` })),
      strong ? h('strong', {}, v.toFixed(3)) : v.toFixed(3));
  }

  // ---------- log ----------
  let logStatus = '';

  $$('#log-filter .chip').forEach((c) => c.addEventListener('click', () => {
    $$('#log-filter .chip').forEach((x) => x.classList.toggle('active', x === c));
    logStatus = c.dataset.status;
    refreshLogs();
  }));

  async function refreshLogs() {
    try {
      const rows = await api('/logs?limit=100' + (logStatus ? '&status=' + logStatus : ''));
      $('#logs-empty').hidden = rows.length > 0;
      $('#logs-body').replaceChildren(...rows.flatMap((r) => {
        const detail = h('tr', { class: 'detail', hidden: true }, h('td', { colspan: 6 },
          h('div', { class: 'detail-body' },
            h('div', {}, h('strong', {}, 'Jawaban: '), r.answer || '-'),
            r.sources.length > 0 && h('div', {}, h('strong', {}, 'Sumber: '), r.sources.map((s) => `[${s.n}] ${s.title}`).join('; ')),
            r.error && h('div', { class: 'error' }, 'Error: ' + r.error),
            h('div', { class: 'muted small-text' }, `${r.latency_ms ?? '-'} ms${r.cached ? ' · cache' : ''}${r.user_ref ? ' · user ' + r.user_ref : ''}`))));
        const row = h('tr', { class: 'clickable', tabindex: '0' },
          h('td', {}, fmtDateTime(r.created_at)),
          h('td', { 'data-label': 'Pertanyaan' }, r.question),
          h('td', { 'data-label': 'Status' }, h('span', { class: 'badge ' + r.status }, STATUS_LABEL[r.status] || r.status)),
          h('td', { class: 'num', 'data-label': 'Skor' }, r.top_score === null ? '-' : r.top_score.toFixed(3)),
          h('td', { 'data-label': 'Kanal' }, r.channel),
          h('td', { 'data-label': 'Feedback' }, r.feedback === 1 ? 'Membantu' : r.feedback === -1 ? 'Tidak membantu' : '-'));
        const toggle = () => { detail.hidden = !detail.hidden; };
        row.addEventListener('click', toggle);
        row.addEventListener('keydown', (e) => { if (e.key === 'Enter') toggle(); });
        return [row, detail];
      }));
    } catch (ex) { toast(ex.message, true); }
  }

  // ---------- ganti password ----------
  $('#btn-password').addEventListener('click', () => {
    $('#password-form').reset();
    showError('#password-error', '');
    $('#dlg-password').showModal();
  });
  $('#password-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const f = e.target;
    try {
      await api('/auth/change-password', { method: 'POST', json: { old_password: f.old_password.value, new_password: f.new_password.value } });
      $('#dlg-password').close();
      toast('Password diganti.');
    } catch (ex) { showError('#password-error', ex.message); }
  });

  // ---------- mulai ----------
  (async function init() {
    if (!token) { showLogin(); return; }
    try {
      const me = await api('/auth/me');
      await enterApp(me.username);
    } catch { showLogin(); }
  })();
})();
