/* Tema panel admin: sistem (ikon gir), terang (matahari), gelap (bulan).
   Dimuat di <head> supaya tema terpasang sebelum halaman tampil (tanpa kedipan). */
(() => {
  'use strict';
  const KEY = 'tk_theme';
  const MODES = ['system', 'light', 'dark'];
  const LABEL = { system: 'Ikuti sistem', light: 'Terang', dark: 'Gelap' };
  const SVG_NS = 'http://www.w3.org/2000/svg';
  const ICONS = {
    system: [
      ['circle', { cx: 12, cy: 12, r: 3 }],
      ['path', { d: 'M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z' }],
    ],
    light: [
      ['circle', { cx: 12, cy: 12, r: 4 }],
      ['path', { d: 'M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41' }],
    ],
    dark: [['path', { d: 'M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z' }]],
  };

  function read() {
    try { const v = localStorage.getItem(KEY); return MODES.includes(v) ? v : 'system'; } catch { return 'system'; }
  }
  function write(mode) { try { localStorage.setItem(KEY, mode); } catch { /* mode tetap berlaku untuk sesi ini */ } }

  function apply(mode) {
    const root = document.documentElement;
    if (mode === 'system') root.removeAttribute('data-theme');
    else root.setAttribute('data-theme', mode);
  }

  function icon(mode) {
    const svg = document.createElementNS(SVG_NS, 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('aria-hidden', 'true');
    for (const [tag, attrs] of ICONS[mode]) {
      const el = document.createElementNS(SVG_NS, tag);
      for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
      svg.append(el);
    }
    return svg;
  }

  let mode = read();
  apply(mode);

  function build() {
    const wrap = document.createElement('div');
    wrap.className = 'theme';
    const menu = document.createElement('div');
    menu.className = 'theme-menu';
    menu.setAttribute('role', 'radiogroup');
    menu.setAttribute('aria-label', 'Tema tampilan');
    menu.hidden = true;
    const main = document.createElement('button');
    main.type = 'button';
    main.className = 'theme-btn';
    main.setAttribute('aria-haspopup', 'true');
    main.setAttribute('aria-expanded', 'false');

    const options = MODES.map((m) => {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'theme-opt';
      b.setAttribute('role', 'radio');
      b.setAttribute('aria-label', LABEL[m]);
      b.title = LABEL[m];
      b.dataset.mode = m;
      b.append(icon(m));
      b.addEventListener('click', () => { choose(m); setOpen(false); main.focus(); });
      return b;
    });
    menu.append(...options);

    function render() {
      main.replaceChildren(icon(mode));
      main.title = 'Tema: ' + LABEL[mode];
      main.setAttribute('aria-label', 'Tema: ' + LABEL[mode] + '. Klik untuk mengubah');
      for (const b of options) b.setAttribute('aria-checked', String(b.dataset.mode === mode));
    }
    function choose(m) { mode = m; write(m); apply(m); render(); }
    function setOpen(open) { menu.hidden = !open; main.setAttribute('aria-expanded', String(open)); }

    main.addEventListener('click', () => setOpen(menu.hidden));
    document.addEventListener('click', (e) => { if (!wrap.contains(e.target)) setOpen(false); });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !menu.hidden) { setOpen(false); main.focus(); } });
    window.addEventListener('storage', (e) => { if (e.key === KEY) { mode = read(); apply(mode); render(); } });

    wrap.append(menu, main);
    document.body.append(wrap);
    render();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', build);
  else build();
})();
