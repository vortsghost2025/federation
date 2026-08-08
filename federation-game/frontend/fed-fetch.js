(function() {
  'use strict';

  var _online = navigator.onLine !== false;
  var _retryTimers = {};

  window.addEventListener('online', function() {
    _online = true;
    showToast('Connection restored', 'ok');
    var pending = Object.keys(_retryTimers);
    for (var i = 0; i < pending.length; i++) {
      clearTimeout(_retryTimers[pending[i]]);
      delete _retryTimers[pending[i]];
    }
    document.dispatchEvent(new CustomEvent('fedFetch:online'));
  });

  window.addEventListener('offline', function() {
    _online = false;
    showToast('Connection lost — offline mode', 'warn');
    document.dispatchEvent(new CustomEvent('fedFetch:offline'));
  });

  window.isFedOnline = function() { return _online; };

  function showToast(msg, type) {
    var container = document.getElementById('toastContainer') || (function() {
      var c = document.createElement('div');
      c.id = 'toastContainer';
      c.style.cssText = 'position:fixed;bottom:1rem;right:1rem;z-index:9999;display:flex;flex-direction:column;gap:0.5rem;pointer-events:none;';
      document.body.appendChild(c);
      return c;
    })();

    var toast = document.createElement('div');
    toast.style.cssText =
      'padding:0.75rem 1rem;' +
      'border-radius:0.5rem;' +
      'font-size:0.875rem;' +
      'font-weight:500;' +
      'max-width:320px;' +
      'box-shadow:0 4px 12px rgba(0,0,0,0.4);' +
      'opacity:0;' +
      'transform:translateY(0.5rem);' +
      'transition:opacity 0.2s ease,transform 0.2s ease;' +
      'pointer-events:auto;' +
      'background:' + (type === 'warn' ? 'rgba(220,80,60,0.95)' : 'rgba(60,160,100,0.95)') + ';' +
      'color:white;' +
      'border:1px solid ' + (type === 'warn' ? 'rgba(220,80,60,0.5)' : 'rgba(60,160,100,0.5)') + ';';
    toast.textContent = msg;
    container.appendChild(toast);

    requestAnimationFrame(function() {
      toast.style.opacity = '1';
      toast.style.transform = 'translateY(0)';
    });

    setTimeout(function() {
      toast.style.opacity = '0';
      toast.style.transform = 'translateY(-0.5rem)';
      setTimeout(function() { toast.remove(); }, 200);
    }, 4000);
  }

  function updateLinkHealth(key, ok) {
    var el = document.getElementById('linkHealth-' + key);
    if (!el) return;
    el.style.background = ok ? 'var(--green)' : 'var(--red)';
    el.title = ok ? 'Connected' : 'Disconnected';
  }

  async function fedFetch(key, url, opts) {
    if (opts === undefined) opts = {};
    var timeout = opts.timeout || 8000;
    var retries = opts.retries !== undefined ? opts.retries : 2;
    var retryDelay = opts.retryDelay || 2000;
    var fetchOpts = {};
    var k;
    var idempotencyKey = opts.idempotencyKey;
    for (k in opts) {
      if (k !== 'timeout' && k !== 'retries' && k !== 'retryDelay' && k !== 'idempotencyKey') fetchOpts[k] = opts[k];
    }
    if (idempotencyKey) {
      fetchOpts.headers = Object.assign({}, fetchOpts.headers || {}, {'X-Idempotency-Key': idempotencyKey});
    }

    if (!_online) {
      showToast(key + ': offline', 'warn');
      updateLinkHealth(key, false);
      document.dispatchEvent(new CustomEvent('fedFetch:error', { detail: { key: key, url: url, error: 'offline' } }));
      return null;
    }

    var attempt = 0;
    while (attempt <= retries) {
      var controller = new AbortController();
      var timer = setTimeout(function() { controller.abort(); }, timeout);
      try {
        var resp = await fetch(url, Object.assign({}, fetchOpts, { signal: controller.signal }));
        clearTimeout(timer);
        if (!resp.ok) throw new Error(resp.status + ' ' + resp.statusText);
        var ct = resp.headers.get('content-type') || '';
        if (ct.includes('text/html')) {
          throw new Error('Server returned HTML instead of JSON (endpoint may be misconfigured)');
        }
        var data = await resp.json();
        updateLinkHealth(key, true);
        return data;
      } catch (e) {
        clearTimeout(timer);
        var msg = e.name === 'AbortError' ? 'Timeout' : e.message;
        attempt++;
        if (attempt <= retries) {
          var delay = Math.min(retryDelay * Math.pow(1.5, attempt - 1), 30000);
          await new Promise(function(r) { setTimeout(r, delay); });
          continue;
        }
        showToast(key + ' failed: ' + msg, 'warn');
        updateLinkHealth(key, false);
        var evt = new CustomEvent('fedFetch:error', { detail: { key: key, url: url, error: msg } });
        document.dispatchEvent(evt);
        return null;
      }
    }
  }

  window.fedFetch = fedFetch;
  window.showToast = showToast;
  window.updateLinkHealth = updateLinkHealth;

  function btnSpinner(btn, label) {
    if (!btn) return function(){};
    var orig = btn.textContent;
    var origDisabled = btn.disabled;
    btn.disabled = true;
    btn.textContent = label || 'Working…';
    btn.setAttribute('aria-busy', 'true');
    return function() {
      btn.textContent = orig;
      btn.disabled = origDisabled;
      btn.removeAttribute('aria-busy');
    };
  }

  function areaSpinner(el, label) {
    if (!el) return function(){};
    var orig = el.innerHTML;
    el.innerHTML = '<div style="padding:1rem;text-align:center;color:var(--fg-muted,rgba(255,255,255,.5))"><span style="display:inline-block;width:1.1em;height:1.1em;border:2px solid rgba(255,255,255,.2);border-top-color:rgba(255,255,255,.7);border-radius:50%;animation:fed-spin .6s linear infinite;vertical-align:middle;margin-right:6px"></span>' + (label || 'Loading…') + '</div>';
    el.setAttribute('aria-busy', 'true');
    return function() {
      el.innerHTML = orig;
      el.removeAttribute('aria-busy');
    };
  }

  if (!document.getElementById('fed-spin-style')) {
    var s = document.createElement('style');
    s.id = 'fed-spin-style';
    s.textContent = '@keyframes fed-spin{to{transform:rotate(360deg)}}';
    document.head.appendChild(s);
  }

  window.btnSpinner = btnSpinner;
  window.areaSpinner = areaSpinner;
})();