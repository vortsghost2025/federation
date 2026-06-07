(function() {
  'use strict';

  function showToast(msg, type) {
    const container = document.getElementById('toastContainer') || (() => {
      const c = document.createElement('div');
      c.id = 'toastContainer';
      c.style.cssText = 'position:fixed;bottom:1rem;right:1rem;z-index:9999;display:flex;flex-direction:column;gap:0.5rem;pointer-events:none;';
      document.body.appendChild(c);
      return c;
    })();

    const toast = document.createElement('div');
    toast.style.cssText = `
      padding:0.75rem 1rem;
      border-radius:0.5rem;
      font-size:0.875rem;
      font-weight:500;
      max-width:320px;
      box-shadow:0 4px 12px rgba(0,0,0,0.4);
      opacity:0;
      transform:translateY(0.5rem);
      transition:opacity 0.2s ease,transform 0.2s ease;
      pointer-events:auto;
      background:${type === 'warn' ? 'rgba(220,80,60,0.95)' : 'rgba(60,160,100,0.95)'};
      color:white;
      border:1px solid ${type === 'warn' ? 'rgba(220,80,60,0.5)' : 'rgba(60,160,100,0.5)'};
    `;
    toast.textContent = msg;
    container.appendChild(toast);

    requestAnimationFrame(() => {
      toast.style.opacity = '1';
      toast.style.transform = 'translateY(0)';
    });

    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateY(-0.5rem)';
      setTimeout(() => toast.remove(), 200);
    }, 4000);
  }

  function updateLinkHealth(key, ok) {
    const el = document.getElementById('linkHealth-' + key);
    if (!el) return;
    el.style.background = ok ? 'var(--green)' : 'var(--red)';
    el.title = ok ? 'Connected' : 'Disconnected';
  }

  async function fedFetch(key, url, opts = {}) {
    const { timeout = 8000, ...fetchOpts } = opts;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);
    try {
      const resp = await fetch(url, { ...fetchOpts, signal: controller.signal });
      clearTimeout(timer);
      if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
      const data = await resp.json();
      updateLinkHealth(key, true);
      return data;
    } catch (e) {
      clearTimeout(timer);
      const msg = e.name === 'AbortError' ? 'Timeout' : e.message;
      showToast(key + ' failed: ' + msg, 'warn');
      updateLinkHealth(key, false);
      return null;
    }
  }

  window.fedFetch = fedFetch;
  window.showToast = showToast;
  window.updateLinkHealth = updateLinkHealth;
})();