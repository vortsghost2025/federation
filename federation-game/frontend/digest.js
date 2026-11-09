/* digest.js — renders GET /simulation/digest as linear prose (2026-11-08).
   Everything is written with textContent so world text can never inject HTML. */
(function () {
  'use strict';

  var content = document.getElementById('content');
  var meta = document.getElementById('meta');

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined && text !== null) e.textContent = String(text);
    return e;
  }

  function fmtTime(ts) {
    var n = parseFloat(ts);
    if (!n) return 'unknown';
    return new Date(n * 1000).toISOString().replace('T', ' ').slice(0, 19) + ' UTC';
  }

  function render(d) {
    content.textContent = '';

    var w = d.world_state || {};
    var stateBits = [];
    ['morale', 'stability', 'threat_level', 'tension_level', 'resource_abundance', 'anomaly_activity'].forEach(function (k) {
      if (w[k] !== undefined && w[k] !== null) stateBits.push(k.replace(/_/g, ' ') + ': ' + w[k]);
    });

    var s1 = el('section');
    s1.appendChild(el('h2', null, 'Simulation status'));
    s1.appendChild(el('p', 'state',
      'Tick ' + (d.tick_id || '?') + ' — ' + (String(d.tick_running) === 'True' ? 'a tick is running now' : 'idle between ticks') + '.'));
    if (d.last_tick_end) s1.appendChild(el('p', null, 'Last tick finished at ' + fmtTime(d.last_tick_end) + '.'));
    s1.appendChild(el('p', null, 'LLM health score: ' + (d.llm_health || 'unknown') + '.'));
    if (stateBits.length) s1.appendChild(el('p', null, 'World state — ' + stateBits.join('; ') + '.'));
    if (d.cascade_temperature !== null && d.cascade_temperature !== undefined) {
      s1.appendChild(el('p', null, 'Event cascade temperature: ' + d.cascade_temperature + '.'));
    }
    content.appendChild(s1);

    if (d.recent_events && d.recent_events.length) {
      var s2 = el('section');
      s2.appendChild(el('h2', null, 'Recent events'));
      var ul = el('ul');
      d.recent_events.forEach(function (t) { ul.appendChild(el('li', null, t)); });
      s2.appendChild(ul);
      content.appendChild(s2);
    }

    var c = d.councilors || {};
    var s3 = el('section');
    s3.appendChild(el('h2', null, 'The councilors — Archimedes Prime and The Oracle'));
    var rows = [
      ['Shared goal', c.shared_goal],
      ['Current topic', c.current_topic],
      ['Open question', c.open_question],
      ['Archimedes is focused on', c.focus_char_001],
      ['The Oracle is focused on', c.focus_char_306],
      ['Last action', c.last_action ? (c.last_action + (c.last_actor ? ' by ' + c.last_actor : '')) : null],
      ['Last message', c.last_message_preview]
    ];
    rows.forEach(function (r) {
      if (r[1]) s3.appendChild(el('p', null, r[0] + ': ' + r[1]));
    });
    content.appendChild(s3);

    var s4 = el('section');
    s4.appendChild(el('h2', null, 'For you'));
    s4.appendChild(el('p', null, 'Messages waiting in your moderator inbox: ' + (d.moderator_inbox_messages || 0) + '.'));
    content.appendChild(s4);

    meta.textContent = 'Digest generated ' + fmtTime(d.generated_at) + ' — refreshes every 60 seconds.';
  }

  function load() {
    var fetchFn = (typeof apiFetch === 'function') ? apiFetch : fetch;
    Promise.resolve(fetchFn('/simulation/digest?format=json', 15000))
      .then(function (d) { if (d && !d.detail) render(d); else throw new Error('bad response'); })
      .catch(function (err) {
        content.textContent = '';
        content.appendChild(el('p', 'err', 'Could not load the digest: ' + err + '. Retrying in 60 seconds.'));
      });
  }

  load();
  setInterval(load, 60000);
})();
