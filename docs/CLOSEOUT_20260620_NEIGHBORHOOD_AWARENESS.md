# Closeout 2026-06-20: Councilor Neighborhood Awareness

## What was added

Three components layered on top of the existing `_neighborhood_snapshot()` (committed in `c3b7b26`):

1. **`_top_neighborhood_npcs(r, n=3)`** — lightweight Redis scan returning top-N most notable NPCs as a comma-separated string. Duplicates the `npc_state:*` scan from `_neighborhood_snapshot()` but only formats the top 3 entries for inline constraint injection.

2. **`_most_common_topic_word(titles)`** — detects topic fixation by counting content words across artifact titles. Fires only when the same word appears in ALL of the last 3 titles (`top_count >= len(titles)`), preventing false positives on legitimate multi-artifact investigations.

3. **Force constraint integration in `decide_action()`**:
   - **Dedup cooldown redirect** (≥2 dedup blocks): appends specific neighborhood NPC names as investigation targets. Previously just said "write something different." Now says "Your neighborhood scan shows these NPCs in notable states: Dr. Prometheus: frustrated; Shadowborn: suspicious."
   - **Topic fatigue redirect** (last 3 artifacts share keyword): appends same NPC hint with pivot instruction.

## What was verified

| Check | Result |
|-------|--------|
| Snapshot size ~400 chars | Confirmed: 385–406 chars in production logs |
| Redis scan bounded | 39 `npc_state:*` keys, ~6ms per scan |
| No secrets leaked | Only reads `npc_state.*` (status/corruption/rumor) + `npc_mood` |
| Self/partner excluded | `cid == CHAR_ID or cid == partner_id` on line 281/391 |
| Pair loop intact | PARTNER ANSWER OBLIGATION appended after all neighborhood constraints (line 1476) |
| Topic fatigue threshold | Requires same word in ALL 3 last titles — conservative |
| Syntax check | `python -m py_compile` clean |
| md5 across all copies | `0f41464026c7e5c5ac443787c6ac59ca` matches host, 001, 306 |

## Observed result

Before: Archimedes + Oracle produce only Void Oracle artifacts, dedup-block each other, retry.
After (first 6 post-deploy ticks):

- **Oracle**: Void Oracle → dedup-blocked → **investigate General Devastation** → **artifact: Economic Implications of Corruption on Faction Stability**
- **Archimedes**: **Charter of Federation Continuity** → **Methodology for Translating Prophetic Vision into Governance** → State of the Federation

Both agents now produce broader, non-Void-Oracle artifacts. The two-person closed loop is broken.

## Deployment notes

- VPS host: `srv1345984.hstgr.cloud` (187.77.3.56)
- Deploy: `scp` → `docker compose restart` on both NPC containers
- Mount mode: **bind-mounted** (`/docker/federation-game/npc-agent:/app:ro`) — no rebuild required
- md5 verified on host and both running containers post-deploy

## Cost note

`_top_neighborhood_npcs()` duplicates the full `npc_state:*` KEYS scan that `_neighborhood_snapshot()` already runs. On a dedup-cooldown+topic-fatigue tick, this runs 3 full scans. At 39 keys × ~6ms each, this is irrelevant for current scale. If the roster grows past ~200 NPCs, the two functions should share a cached scan result.

## Files

- `federation-game/npc-agent/npc_agent.py` — all changes
