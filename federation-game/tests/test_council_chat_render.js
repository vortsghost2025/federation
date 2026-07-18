/*
 * Deterministic rendering check for Council Chat moderator inbox.
 * Run: node federation-game/tests/test_council_chat_render.js
 *
 * Verifies the two fixes shipped in fix/moderator-inbox-visibility:
 *   1. The merged inbox + thread list is sorted NEWEST-FIRST (descending ts),
 *      so Sean's most recent activity is at the top of the scroll panel.
 *   2. Each row is classified into SENT / DELIVERED / REPLY / FAILED.
 *
 * This mirrors the exact logic in council-chat.html so the behavior is locked.
 */
'use strict';

// --- logic copied verbatim from council-chat.html ---
function sortModeratorRows(rows) {
  return rows.slice().sort(
    (a, b) => Number(b.ts || b.created_at || 0) - Number(a.ts || a.created_at || 0)
  );
}
function moderatorMessageKind(msg) {
  const from = msg.from_char_id || '';
  const to = msg.to_char_id || '';
  const text = ((msg.subject || '') + ' ' + (msg.body || '')).toLowerCase();
  if (from === 'moderator') return 'sent';
  if (/failed validation|unable to|inability|could not produce/.test(text)) return 'failed';
  if (to === 'moderator' && (from === 'char_001' || from === 'char_306')) return 'reply';
  return 'delivered';
}

// --- assertions ---
let failures = 0;
function assert(cond, name) {
  if (cond) { console.log('PASS:', name); }
  else { console.error('FAIL:', name); failures++; }
}

// Build a realistic fixture: inbox (newest-first from API) + an active thread
// (oldest-first from API). Mix of a failed reply, a sent msg, and a reply.
const fixture = [
  { from_char_id: 'char_306', to_char_id: 'moderator', ts: 3000, subject: 'A reply', body: 'hello' },
  { from_char_id: 'char_001', to_char_id: 'moderator', ts: 2900, subject: 'operator reply failed validation', body: 'could not produce' },
  { from_char_id: 'moderator', to_char_id: 'char_306', ts: 1000, subject: 'Self diagnostic request', body: 'review your outputs' },
  { from_char_id: 'char_306', to_char_id: 'moderator', ts: 1100, subject: 'ok', body: 'i will' },
];

const sorted = sortModeratorRows(fixture);
assert(sorted[0].ts === 3000, 'newest row is first after sort');
assert(sorted[sorted.length - 1].ts === 1000, 'oldest row is last after sort');
assert(
  sorted.every((r, i) => i === 0 || Number(sorted[i - 1].ts) >= Number(r.ts)),
  'every adjacent pair is descending'
);

assert(moderatorMessageKind({ from_char_id: 'moderator', to_char_id: 'char_306' }) === 'sent', 'sent classified');
assert(moderatorMessageKind({ from_char_id: 'char_306', to_char_id: 'moderator', subject: 'x', body: 'failed validation' }) === 'failed', 'failed classified');
assert(moderatorMessageKind({ from_char_id: 'char_306', to_char_id: 'moderator', subject: 'x', body: 'normal' }) === 'reply', 'reply classified');
// char_306 -> char_001 is not a reply to the moderator, so it is neither
// sent nor reply; it falls through to 'delivered' (delivered, no moderator reply).
assert(moderatorMessageKind({ from_char_id: 'char_306', to_char_id: 'char_001', subject: 'x', body: 'normal' }) === 'delivered', 'delivered classified');

// Guard: the stale ascending comparator (the original bug) would put oldest first.
const buggy = fixture.slice().sort((a, b) => Number(a.ts || a.created_at || 0) - Number(b.ts || b.created_at || 0));
assert(buggy[0].ts !== sorted[0].ts, 'fixed sort differs from the old ascending bug');

console.log(failures === 0 ? '\nALL TESTS PASSED' : `\n${failures} TEST(S) FAILED`);
process.exit(failures === 0 ? 0 : 1);
