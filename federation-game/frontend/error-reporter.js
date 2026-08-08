(function() {
  'use strict';

  /* ------------------------------------------------------------------
   * Error Reporter - captures browser errors for agent analysis.
   * Include AFTER fed-fetch.js on each page.
   *
   * Captures:
   *   - Uncaught JS errors
   *   - Unhandled promise rejections
   *   - Reporting API events (deprecation, intervention, csp-violation)
   *   - Fetch failures (patches global fetch)
   *
   * Sends to backend /error-reports for agent querying.
   * Batches reports to avoid flooding.
   * ------------------------------------------------------------------ */

  var REPORT_URL = '/error-reports';
  var _queue = [];
  var _flushing = false;
  var _enabled = true;

  function sendToBackend(report) {
    if (!_enabled) return;
    _queue.push(report);
    if (!_flushing) {
      _flushing = true;
      setTimeout(flushQueue, 1000);
    }
  }

  function flushQueue() {
    var batch = _queue.splice(0);
    _flushing = false;
    if (batch.length === 0) return;

    try {
      var body = JSON.stringify({
        reports: batch,
        url: window.location.href,
        timestamp: new Date().toISOString(),
        userAgent: navigator.userAgent
      });
      // Use raw fetch (not fedFetch) to avoid circular reporting
      var xhr = new XMLHttpRequest();
      xhr.open('POST', REPORT_URL, true);
      xhr.setRequestHeader('Content-Type', 'application/json');
      xhr.onerror = function() {
        _queue = batch.concat(_queue);
        if (_queue.length > 200) _queue = _queue.slice(-200);
      };
      xhr.onreadystatechange = function() {
        if (xhr.readyState === 4 && xhr.status === 404) {
          _enabled = false;
        }
      };
      xhr.send(body);
    } catch(e) {
      // silently swallow — can't report errors about the error reporter
    }
  }

  // 1. Uncaught JS errors
  window.onerror = function(msg, source, line, col, error) {
    sendToBackend({
      type: 'js-error',
      message: typeof msg === 'object' ? String(msg) : msg,
      source: source || '',
      line: line || 0,
      col: col || 0,
      stack: error && error.stack ? error.stack.slice(0, 1000) : ''
    });
  };

  // 2. Unhandled promise rejections
  window.addEventListener('unhandledrejection', function(e) {
    var reason = e.reason || {};
    sendToBackend({
      type: 'unhandled-rejection',
      message: reason.message || String(reason).slice(0, 500),
      stack: reason.stack ? reason.stack.slice(0, 1000) : ''
    });
  });

  // 3. ReportingObserver (deprecations, interventions, CSP violations)
  if (window.ReportingObserver) {
    try {
      var observer = new ReportingObserver(function(reports) {
        for (var i = 0; i < reports.length; i++) {
          var r = reports[i];
          sendToBackend({
            type: 'reporting-' + r.type,
            body: r.body ? JSON.stringify(r.body).slice(0, 2000) : '',
            sourceFile: r.url || ''
          });
        }
      }, { types: ['deprecation', 'intervention', 'csp-violation'] });
      observer.observe();
    } catch(e) {
      // ReportingObserver not supported
    }
  }

  // 4. Patch fetch to catch network failures
  var _origFetch = window.fetch;
  if (_origFetch) {
    window.fetch = function(input, init) {
      return _origFetch.call(window, input, init).catch(function(err) {
        var url = typeof input === 'string' ? input :
                  (input && input.url ? input.url : String(input));
        sendToBackend({
          type: 'fetch-failure',
          url: url.slice(0, 500),
          error: err.message || String(err)
        });
        throw err;
      });
    };
  }

  // 5. Listen for fedFetch failures via custom event (if fedFetch is loaded)
  document.addEventListener('fedFetch:error', function(e) {
    sendToBackend({
      type: 'fedfetch-failure',
      key: e.detail && e.detail.key ? e.detail.key : '',
      url: e.detail && e.detail.url ? e.detail.url : '',
      error: e.detail && e.detail.error ? e.detail.error : ''
    });
  });
})();