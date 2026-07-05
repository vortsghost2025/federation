# Stage 5 — NPC Self-Correcting Meta-Layer

**Status:** Design / Not Implemented
**Date:** 2026-07-05
**Source:** WE4FREE Papers A–F, Book 6, CAISC Self-State Aliasing, Pattern Decision Tree
**Anchor:** `_compute_convergence_state` L610 | `npc_decisions.py` force_constraint | Stage 4C plateau_count ≥ 3

---

## 1. Core Thesis

### NPC Behavior Phenotypes

NPC conversations are the Federation's phenotype registry. Every `decide_action()` output is a phenotype — a behavioral regularity that emerges from the intersection of personality constraints, faction alignment, relationship scores, topic availability, and event pressure. The 11 `AGENCY_CATEGORIES` (investigate, create_artifact, send_message, rest, etc.) are the observable phenotype classes.

An unwanted phenotype (resonance loop, topic stall, pseudo-disagreement plateau) is not a "bug." It is evidence that the constraint lattice is missing a constraint that would have selected against that behavior.

### Constraint Lattice

The NPC's constraint lattice is currently assembled ad-hoc each tick inside `force_constraint`: streak counters, dedup thresholds, cooldown timers, topic fatigue counts, convergence state, partner obligation rules. It works — the resonance loop is closed — but the lattice has no observable structure. Constraints are injected as prompt text. There is no registry of which constraints exist, which are active, or which were added in response to which failure.

### Self-State Aliasing (NFM-002 analog)

An NPC cannot directly observe "am I stuck?" It observes artifacts — message counts, streak lengths, topic cooldowns — and infers from these whether it is looping. This is the same pattern as the Archivist incident: inferring state from stale coordination artifacts rather than live runtime. The NPC infers "I am having a substantive conversation" from artifact patterns that actually indicate a pseudo-disagreement plateau.

### Drift Detection

The NPC system detects three types of drift internally: topic drift (most_common_topic_word ≥ 3), behavioral drift (newest_first_streak ≥ 3 same category), and social drift (unanswered open question stalls). Each triggers a constraint injection. But no single mechanism observes all three drift types simultaneously or tracks whether drift is increasing or decreasing across the NPC population.

### Self-Correcting Loop

The WE4FREE self-correcting loop:

```
Failure → Detection → Correction → Constraint Refinement → New Stable State
```

The NPC system currently implements:

```
Failure → Detection → Correction  
                             ↑ manual — constraint refinement is code deployment
```

Stage 4C closed one loop: pseudo-disagreement plateau → convergence_state plateau_count → resolved. But the loop terminates at `resolved: true`. It does not feed back into the constraint lattice to prevent similar patterns from emerging in other NPC pairs or with other topic families. That feedback is the missing architecture.

---

## 2. Current Code Equivalents

| Paper F Concept | NPC Code Equivalent | Location |
|-----------------|---------------------|----------|
| Constraint lattice | `force_constraint` builder — 8+ constraint categories injected into LLM system prompt every tick | `npc_decisions.py:350–618` |
| Phenotype selection | `AGENCY_CATEGORIES` (11 action types) + post-parse overrides (7 override gates) | `npc_decisions.py:166–177, 651–772` |
| Self-state aliasing guard | `_consecutive_send_streak`, `_artifact_count`, `_send_count` — NPC reads own Redis counters | `npc_decisions.py:181–265` |
| Drift detection (topic) | `_most_common_topic_word` — ≥ 3 same topic across recent decisions triggers cooldown | `npc_decisions.py:427–514` |
| Drift detection (behavior) | `_newest_first_streak` — ≥ 3 same category triggers loop-break constraint | `npc_decisions.py:606–618` |
| Drift detection (social) | Open question stall detection, partner state question | `npc_decisions.py:515–560` |
| Convergence state | `_compute_convergence_state` — LLM extracts shared understanding from both partners | `npc_redis_helpers.py:610–751` |
| Plateau check | `_is_no_substantive_disagreement` + `_is_pseudo_framing_disagreement` + `_matched_loop_topic` | `npc_redis_helpers.py:34–83` |
| Resolution | `plateau_count >= 3 → resolved: true, blocked_topic_terms populated` | `npc_redis_helpers.py:709–730` |
| Pattern decision tree | Implicit in `force_constraint` branches | `npc_decisions.py:350–618` |

### What These Give Us

The system already has the machinery for plates 1–4 of the self-correcting loop:

1. **Failure event** — an NPC produces a decision that matches a known loop pattern (topic fatigue ≥ 3, streak ≥ 4, plateau_count incrementing)
2. **Detection** — `force_constraint` reads the RSSI of loop signals and injects a constraint into the next tick's prompt
3. **Correction** — post-parse overrides enforce the constraint even if the LLM ignores it
4. **Constraint refinement** — MISSING. The constraint is injected ephemerally into a prompt. It does not persist across sessions, does not propagate to other NPCs, and does not become a permanent lattice element.

---

## 3. Missing Architecture

### Constraint Refinement Feedback

When Stage 4C added `_matched_loop_topic()` and `_is_pseudo_framing_disagreement()` to `npc_redis_helpers.py`, it permanently refined the constraint lattice for all NPC pairs. But there was no mechanism — within the system — that would have allowed the system to discover this refinement on its own.

The missing mechanism:
- A constraint that is effective in one NPC pair should be available for all NPC pairs to discover
- A constraint that resolves a failure class should be stored permanently, not re-invented per tick
- A constraint that is ineffective should produce evidence of ineffectiveness

### NPC Behavioral Health Gate

The WE4FREE system has `FORMAL_VERIFICATION_GATE_PHASE*.md` — a structured compliance check applied before every change. The NPC system has no equivalent. There is no check that answers:

- Is this NPC conversation healthy?
- Is this NPC pair making progress?
- Is the constraint lattice for this NPC complete?

### Cross-NPC Observability (OL-2 Analog)

`_compute_convergence_state` only runs per-pair. NPC 001-1 cannot observe NPC 306-1's behavioral health directly — it reads the shared convergence_state hash and the pair workspace, but those are conversation-level artifacts, not health-level. One NPC cannot detect another NPC's loop unless the loop manifests in a message to them.

This is **OL-2: source-of-truth is distributed** applied to NPC cognition. No single NPC holds a complete view of the system's behavioral health. Convergence requires an observer outside any single NPC.

### Failure-Class Registry

The papers have 35 named NFMs across 8 categories. The NPC system has unnamed failure modes embedded as checks:
- Send-message streak ≥ 2 (no NFM equivalent)
- Topic fatigue ≥ 3 (no NFM equivalent)
- Behavioral shape loop ≥ 4 (no NFM equivalent)
- Open question stall (no NFM equivalent)
- Pseudo-disagreement plateau ≥ 3 (no NFM equivalent)

None have a stable identifier. None are tracked across sessions. None are counted.

### Pattern Decision Tree for NPC Loops

The `PATTERN_DECISION_TREE.md` in the verification directory has 8 decision trees for the WE4FREE system. The NPC system needs a similar document:

| Symptom | Detection | Threshold | Intervention |
|---------|-----------|-----------|--------------|
| Repeated same topic | topic_fatigue | ≥ 3 same root word in window | Apply topic cooldown, block create_artifact |
| Repeated same action | behavioral_shape | ≥ 4 same category | Force rest, force new category |
| Pseudo-disagreement | convergence disagreement check | plateau_count ≥ 3 | Set resolved=true, populate blocked_terms |
| Unanswered question | open_question timestamp | partner_answered=False AND no work produced | Force answer obligation |
| Repeating artifact | _is_repetitive_artifact | Jaccard ≥ 0.55 vs last 5 | Block create_artifact on that topic |

---

## 4. Proposed Stage 5 Components

### 4.1 NPCBehaviorObserver

A read-only process that watches NPC decision output from Redis. It does not edit code, does not modify NPC behavior, and does not inject into the LLM prompt. It observes:

- Per-NPC: decision category distribution over a sliding window (last 50 decisions)
- Per-NPC: topic_fatigue events, cooldown activations, plateau_count changes
- Per-NPC: behavioral shape streaks and their resolutions
- Per-pair: convergence_state version, plateau_count, resolved/unresolved transitions
- Cross-NPC: same-topic correlation, behavioral pattern similarity

Output: structured observation log written to a Redis hash or a file.

**Boundary:** Observer has read-only Redis connection. No write keys. No NPC-side code changes.

### 4.2 NPCPhenotypeRegistry

A structured registry of observed NPC behavior patterns. For each NPC pair or individual:

```json
{
  "pair_id": "char_001-306",
  "observed_at": "2026-07-05T00:40:00Z",
  "phenotype_distribution": {
    "send_message": 12,
    "create_artifact": 8,
    "investigate": 5,
    "read_artifacts": 4,
    "rest": 3
  },
  "active_constraints": [
    "topic_cooldown:structured_resonance_lattice",
    "behavioral_loop_break:streak_4"
  ],
  "failure_events": [
    {
      "class": "topic_loop",
      "topic": "resonance",
      "count": 7,
      "resolution": "plateau_resolved"
    }
  ],
  "health_score": 0.72
}
```

**Boundary:** Registry is write-once, append-only. No deletions. No modifications to existing entries.

### 4.3 NPCFailureClassifier

Classifies observed behavior patterns against a failure taxonomy derived from the WE4FREE NFM categories:

| Federation NFM Class | Parent NFM Category | Description |
|----------------------|---------------------|-------------|
| FED-NFM-001 | State-Claim | NPC claims substantive conversation while producing pseudo-disagreement |
| FED-NFM-002 | Schema-Reality | NPC's behavior does not match its decision category |
| FED-NFM-003 | Drift | NPC topic distribution drifts from faction/persona baseline |
| FED-NFM-004 | Observability | NPC cannot detect its own loop (self-state aliasing) |
| FED-NFM-005 | Enforcement | force_constraint is ignored by LLM, post-parse must override |
| FED-NFM-006 | Timeout | NPC takes >30s to produce decision (stall) |
| FED-NFM-007 | Platform | Redis inconsistency between paired NPC convergence states |
| FED-NFM-008 | Delegation | Cross-NPC question/answer loop with no progress |

**Boundary:** Classifier recommends a class with confidence. It does not apply interventions.

### 4.4 ConstraintRefinementQueue

A queue of candidate constraint refinements derived from persistent failure observations. Each refinement is paired with its evidence and remains in PENDING until approved (by human or by automated gate).

```json
{
  "refinement_id": "CRQ-2026-07-05-001",
  "source_failure": "FED-NFM-001",
  "evidence": "char_001-306 plateau_count reached 3 on resonance topic, pseudo_framing detected 6 times",
  "recommended_constraint": "Add _matched_loop_topic() and _is_pseudo_framing_disagreement() to convergence checks",
  "target_component": "npc_redis_helpers.py:_compute_convergence_state",
  "intervention_level": "hypothesis",
  "status": "PENDING",
  "confidence": 0.88,
  "approved_at": null,
  "deployed_at": null
}
```

**Boundary:** Queue items are never auto-deployed. They are recommendations with confidence scores.

### 4.5 NPCMetaHealthReport

A periodic report summarizing the behavioral health of the NPC system:

- Total NPC pairs observed
- Pairs with active convergence (plateau_count = 0)
- Pairs approaching resolution (plateau_count = 1 or 2)
- Pairs resolved (plateau_count ≥ 3, resolved = true)
- Active FED-NFM failure counts
- Constraint refinement queue length
- Pending approvals
- Health trend (improving, degrading, stable)

Generated every N observation cycles. Readable by human operator.

### 4.6 Human Approval Gate (Optional)

For constraint refinements that modify NPC code (as opposed to ephemeral prompt injections), an approval gate that:

1. Receives a ConstraintRefinementQueue item
2. Verifies evidence path (which NPC, which failure, which constraint)
3. Checks that the proposed constraint does not duplicate an existing one
4. Checks that the proposed constraint does not contradict an existing one
5. Presents to human for approve/reject/modify
6. On approval: writes to a deploy queue
7. On reject: logs rejection reason, archives the refinement

---

## 5. Data Model

### ObservedBehavior

| Field | Type | Description |
|-------|------|-------------|
| `observation_id` | UUID | Unique identifier |
| `timestamp` | ISO 8601 | When observed |
| `npc_ids` | string[] | NPCs involved |
| `pair_id` | string | Pair identifier (if applicable) |
| `behavior_type` | enum | topic_loop, behavioral_loop, pseudo_disagreement, open_question_stall, artifact_dedup, send_message_streak, convergence_success, convergence_plateau, convergence_resolved |
| `raw_evidence` | JSON | Decision shapes, topic terms, streak counts, plateau counts |
| `failure_class` | enum | FED-NFM-001 through FED-NFM-008 |
| `failure_confidence` | float | 0.0–1.0 |

### SuspectedFailureClass

| Field | Type | Description |
|-------|------|-------------|
| `failure_id` | UUID | Unique identifier |
| `derived_from` | UUID | Observation ID |
| `class_label` | FED-NFM enum | Best match |
| `class_confidence` | float | 0.0–1.0 |
| `alternative_classes` | JSON | Other possible matches with confidences |
| `evidence_summary` | string | Human-readable explanation |

### AffectedNPCs

| Field | Type | Description |
|-------|------|-------------|
| `npc_id` | string | char_001, char_306, etc. |
| `behavior_count` | int | Number of observed events |
| `severity` | enum | low, medium, high, critical |
| `current_convergence_state` | JSON | Latest convergence_state hash content |
| `plateau_count` | int | Current plateau count |
| `resolved` | bool | Whether pair has resolved |
| `blocked_terms` | string[] | Currently blocked topic terms |

### Evidence

| Field | Type | Description |
|-------|------|-------------|
| `sources` | string[] | Redis keys or file paths |
| `raw` | JSON | The raw data at time of observation |
| `chain` | string[] | Sequence of decisions/convergence states leading to failure |
| `duration` | int | How long the pattern persisted (in ticks) |

### RecommendedConstraint

| Field | Type | Description |
|-------|------|-------------|
| `constraint_id` | UUID | Unique identifier |
| `failure_id` | UUID | Source failure |
| `description` | string | Human-readable constraint |
| `target_code` | string | File:function hint |
| `implementation_hint` | string | What the code change should look like |
| `hypothesis` | string | Testable claim: "If we add X, then Y will not recur" |
| `status` | enum | hypothesis, pending, approved, deployed, rejected, superseded |

### InterventionLevel

| Level | Meaning | Action |
|-------|---------|--------|
| `report` | Observation only | Log to NPCMetaHealthReport |
| `prompt` | Ephemeral constraint injection | Add to NPC prompt (force_constraint) |
| `config` | Persistent config change | Update Redis config, no code change |
| `code` | Code change required | Human approval gate required |

### Resolved / Unresolved

| Field | Type | Description |
|-------|------|-------------|
| `failure_id` | UUID | The resolved failure |
| `resolution` | string | How it was resolved (code change, prompt injection, config change, or degraded) |
| `resolved_at` | ISO 8601 | Timestamp |
| `constraint_id` | UUID | The constraint that resolved it |
| `verification` | string | Evidence that it stayed resolved for N observation cycles |

---

## 6. Safety Boundaries

### Observer Does Not Edit Code

`NPCBehaviorObserver` has read-only Redis access and read-only filesystem access. It cannot write to any Redis key that an NPC reads for decision-making. It cannot modify `npc_decisions.py`, `npc_redis_helpers.py`, `npc_context.py`, or any other NPC code file. It cannot spawn NPC processes.

### Observer Does Not Auto-Deploy

Constraint refinements from `ConstraintRefinementQueue` with `intervention_level: code` require human approval before any deployment action. No automated pipeline pushes recommendations to production. No automated pipeline restarts NPC containers.

### Observer Only Recommends Constraints First

The first output of any failure observation is a `RecommendedConstraint` with `status: hypothesis`. The recommendation must specify:
- Which constraint to add
- Where to add it (which file, which function)
- What observable outcome it predicts ("If X is added, Y will not recur for at least Z ticks")
- What would falsify the hypothesis ("Y recurs within Z ticks despite X")

### Generated Recommendations Must Be Labeled Hypothesis

Every `RecommendedConstraint` carries an explicit hypothesis label:

```json
{
  "status": "hypothesis",
  "verification_condition": "Observe char_001-306 for 100 ticks after deployment. If plateau_count reaches 3 again without pseudo_disagreement, hypothesis is falsified.",
  "falsification_count": 0
}
```

A hypothesis that has been falsified more than twice for the same failure class in the same NPC pair should be escalated — it may be the wrong constraint for that failure.

---

## 7. First Safe Implementation Phase

### Scope

- One read-only observer process
- Watches exactly 2 NPCs (001-1 and 306-1 — the existing pair)
- Runs alongside existing NPC code without modification
- Logs observations to file and terminal
- No behavior changes to any NPC
- No Redis writes on NPC keys
- No new Redis keys written
- No Docker restart
- No code deployment

### What It Observes

Only one Redis key is verified from the current codebase (`npc_redis_helpers.py:469`):

| Redis Key | Verified? | How to Access |
|-----------|-----------|--------------|
| `npc_pair:char_001__char_306:state` field `convergence_state` | ✅ Verified | `HGET npc_pair:char_001__char_306:state convergence_state` |

All other Redis keys the observer needs (decision history, mood, inbox/outbox patterns) must be verified from code before implementation. The read-only observer can discover them by scanning `npc_redis_helpers.py` and `npc_agent.py` for `r.xxx(...)` calls, but should log a warning on startup for any key it is configured to read but cannot verify exists in the codebase.

**Implementation note for fresh agents:** Do not assume Redis key patterns. Read `npc_redis_helpers.py` and `npc_decisions.py` to extract exact key strings before writing observer code. Prefer `redis.scan_match()` with a known prefix (e.g., `npc_pair:*`) over hardcoded key names where possible.

### What It Reports

For each observation cycle (every 60s — twice the NPC tick rate):

```
[OBSERVE] char_001: streak=2, arts=1, fatigue_topic=none, shape=[send,create,rest], conv_state_version=12
[OBSERVE] char_306: streak=0, arts=3, fatigue_topic=resonance, shape=[read,create,create], conv_state_version=12
[OBSERVE] pair 001-306: plateau_count=0, resolved=false, agreement="discussing resonance effects", disagreement="no clear disagreement"
[HEALTH] pair 001-306: active. plateau trend: stable. behavioral diversity: 0.64. loop risk: low.
```

At the end of each observation window (default: 50 cycles, ~50 minutes of NPC runtime):

```
[META] — Observation Window Summary — 50 cycles (50:23 elapsed)
[META] char_001: 45 decisions. distribution: send=18, create=12, investigate=8, read=5, rest=2
[META] char_306: 43 decisions. distribution: create=20, read=10, send=8, investigate=3, rest=2
[META] pair 001-306: 3 plateaus, 0 resolutions. avg plateau_count=0.6.
[META] Failure events: 2 topic_fatigue (char_306, term: resonance)
[META] No persistent failures detected. Constraint lattice appears stable.
[META] Next observation window in 500 ticks.
```

### Success Criteria for Phase 1

- Observer runs for 24 hours without crash
- Observer logs are parseable and clean
- Observer detects a topic_fatigue event within the first observation window
- Observer detects a plateau_count increment (if one occurs)
- Observer produces valid health reports
- Observer consumes < 5% of Redis connection pool
- Observer does not interfere with any NPC decision

### Phase 1 to Phase 2 Gate

Phase 2 (adding `NPCPhenotypeRegistry` and `NPCFailureClassifier`) must not begin until:

- Phase 1 has run for at least 24 hours
- Phase 1 has observed at least one failure event (topic_fatigue, behavioral_loop, or plateau increment)
- Phase 1 logs have been reviewed by human operator
- No NPC behavior changes were attributed to Phase 1

---

*Stage 5 closes the self-correcting loop by adding the missing constraint refinement feedback. It does nothing that an NPC can feel. It only watches, waits, and reports. The first deployable piece is a 200-line Python script with read-only Redis access and a logger.*
