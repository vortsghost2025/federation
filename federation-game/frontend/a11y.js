/* a11y.js — shared accessibility controls for Federation pages.
   Added 2026-11-08 at the operator's request:
   - text-size stepper (A- / A+) persisted in localStorage
   - "Copy text" button that copies the whole page as plain text
   Injected into any page that includes <script src="a11y.js" defer>.
   No dependencies; safe to include on every page. */
(function () {
  'use strict';

  var KEY = 'fed_font_px';
  var MIN = 14, MAX = 32, STEP = 2, DEFAULT = 16;

  function saved() {
    try {
      var v = parseInt(localStorage.getItem(KEY) || '', 10);
      if (v >= MIN && v <= MAX) return v;
    } catch (e) { /* storage unavailable */ }
    return null;
  }

  function apply(px) {
    if (px) {
      document.documentElement.style.fontSize = px + 'px';
    } else {
      document.documentElement.style.removeProperty('font-size');
    }
    try { localStorage.setItem(KEY, px ? String(px) : ''); } catch (e) { /* ignore */ }
    var lbl = document.getElementById('a11y-size-label');
    if (lbl) lbl.textContent = px ? px + 'px' : 'auto';
  }

  function current() {
    var s = saved();
    if (s) return s;
    var c = parseInt(getComputedStyle(document.documentElement).fontSize, 10);
    return (c >= MIN && c <= MAX) ? c : DEFAULT;
  }

  function step(d) {
    apply(Math.min(MAX, Math.max(MIN, current() + d)));
  }

  function copyPage() {
    var text = (document.body && document.body.innerText) || '';
    var btn = document.getElementById('a11y-copy');
    function done(ok) {
      if (!btn) return;
      btn.textContent = ok ? '✓ Copied' : '✗ Copy failed';
      btn.setAttribute('aria-label', ok ? 'Page copied as plain text' : 'Copy failed');
      setTimeout(function () {
        btn.textContent = '⧉ Copy text';
        btn.setAttribute('aria-label', 'Copy this page as plain text');
      }, 1800);
    }
    function fallback() {
      var ta = document.createElement('textarea');
      ta.value = text;
      ta.setAttribute('readonly', '');
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      var ok = false;
      try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
      document.body.removeChild(ta);
      done(ok);
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () { done(true); }, fallback);
    } else {
      fallback();
    }
  }

  function build() {
    if (document.getElementById('a11y-bar')) return;
    var style = document.createElement('style');
    style.textContent =
      '#a11y-bar{position:fixed;right:10px;bottom:10px;z-index:99999;display:flex;gap:6px;' +
      'align-items:center;background:#0c1018;border:2px solid #3a5a80;border-radius:10px;' +
      'padding:6px 8px;font-family:inherit;box-shadow:0 4px 18px rgba(0,0,0,.6)}' +
      '#a11y-bar button{min-width:44px;min-height:44px;font-size:1.15rem;font-weight:700;' +
      'background:#1a2430;color:#e8f0fa;border:1px solid #3a5a80;border-radius:8px;cursor:pointer}' +
      '#a11y-bar button:hover,#a11y-bar button:focus-visible{background:#27384f;outline:2px solid #7aa7ff;outline-offset:1px}' +
      '#a11y-size-label{color:#9fb4cc;font-size:.95rem;min-width:44px;text-align:center}';
    document.head.appendChild(style);

    var bar = document.createElement('div');
    bar.id = 'a11y-bar';
    bar.setAttribute('role', 'toolbar');
    bar.setAttribute('aria-label', 'Display size and copy controls');

    var dec = document.createElement('button');
    dec.id = 'a11y-dec';
    dec.textContent = 'A−';
    dec.setAttribute('aria-label', 'Make text smaller');
    dec.title = 'Smaller text';
    dec.addEventListener('click', function () { step(-STEP); });

    var lbl = document.createElement('span');
    lbl.id = 'a11y-size-label';
    lbl.setAttribute('aria-live', 'polite');

    var inc = document.createElement('button');
    inc.id = 'a11y-inc';
    inc.textContent = 'A+';
    inc.setAttribute('aria-label', 'Make text larger');
    inc.title = 'Larger text';
    inc.addEventListener('click', function () { step(STEP); });

    var copy = document.createElement('button');
    copy.id = 'a11y-copy';
    copy.textContent = '⧉ Copy text';
    copy.setAttribute('aria-label', 'Copy this page as plain text');
    copy.title = 'Copy the whole page as plain text';
    copy.addEventListener('click', copyPage);

    bar.appendChild(dec);
    bar.appendChild(lbl);
    bar.appendChild(inc);
    bar.appendChild(copy);
    document.body.appendChild(bar);

    apply(saved()); // restores saved size, or clears to auto
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', build);
  } else {
    build();
  }
})();
