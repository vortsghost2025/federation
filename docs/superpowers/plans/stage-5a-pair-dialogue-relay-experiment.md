# Stage 5A: Pair Dialogue Relay Experiment

**Date:** 2026-07-05
**Status:** Design only
**Scope:** Experimental NPC pair architecture

## Core Invariant

Keep the proven pair stable. Test relay cognition on a fresh pair.

## Purpose

Stage 4C and Stage 4D stabilized the current councilor pair. The current
shared-workspace model can remain productive, but recent checks show it still
routes much of the interaction through artifacts, shared goals, and open
questions rather than clean back-and-forth dialogue.

Stage 5A designs a safe experiment for direct pair conversation without
modifying the proven pair.

## Experiment Shape

### A. Federation Control Pair

```text
char_001 + char_306
Model: existing shared-workspace cognition
Status: Stage 4C/4D stabilized
Rule: do not modify for Stage 5A
```

### B. Federation Relay Pair

```text
new persistent NPC A + new persistent NPC B
Model: Pair Dialogue Relay
Rule: exact-message forwarding, not summary forwarding
```

Placeholder IDs:

```text
char_501 = The Correspondent
char_502 = The Respondent
```

These are placeholders only. Before implementation, registry-check NPC IDs so
they do not collide with existing persistent NPCs.

### C. Genesis Baseline

```text
Genesis sim behavior
Model: external comparison baseline
Purpose: compare natural conversation dynamics
```

## Core Rule

When two NPCs need to talk, stop making conversation emerge from shared state.
Forward the exact last message to the next speaker.

Keeper sentence:

```text
The system does not reinterpret the message. It acts as the postman.
```

## Relay Thread Data Model

Suggested Redis-style state key:

```text
npc_pair:<npc_a>__<npc_b>:relay
```

Suggested fields:

```text
relay_status = inactive | active | resolved | expired | blocked
relay_thread_id
relay_turn_count
relay_max_turns
relay_next_speaker
relay_last_speaker
relay_last_message
relay_last_message_ts
relay_started_reason
relay_started_at
relay_resolved_at
relay_resolution_summary
relay_stop_reason
relay_topic
relay_exact_transcript
artifact_pause_active = true | false
```

The critical field is `relay_last_message`. It stores exact text, not a
summary, interpretation, or derived prompt.

## Exact-Message Forwarding Flow

```text
1. NPC A speaks.
2. System stores the exact text as relay_last_message.
3. System sets relay_next_speaker = NPC B.
4. NPC B receives relay_last_message as primary prompt context.
5. NPC B replies directly to that exact text.
6. System stores the exact reply.
7. System sets relay_next_speaker = NPC A.
8. Repeat until resolved or capped.
```

The relay layer should be a transport layer, not a third participant in the
conversation.

## Activation Conditions

Relay mode should activate only for the new experiment pair, and only when a
direct answer is useful.

Candidate activation conditions:

```text
pair is the experimental relay pair
relay_status is inactive
open_question exists or seed prompt exists
convergence_state.resolved is false
direct answer is needed
artifact repetition is forming
```

Relay mode must not activate for `char_001/char_306` during Stage 5A. They are
the control group.

## Artifact Pause Rule

During active relay:

```text
artifact creation is paused or strongly discouraged
```

Preferred actions:

```text
send_message
ask_clarifying_question
answer_partner
summarize_resolution
```

Discouraged actions while relay is active:

```text
create_artifact
create_institution
propose_role
write_code
self_improve
```

Reason: artifact creation lets the NPC avoid direct conversation. Relay mode is
specifically testing whether exact-message turn-taking creates more natural
dialogue.

## Turn Cap And Stop Conditions

Recommended initial cap:

```text
relay_max_turns = 8
```

This gives four turns per NPC, enough to test dialogue without allowing an
infinite loop.

Stop conditions:

```text
resolved = true
relay_turn_count >= relay_max_turns
same-topic repetition exceeds threshold
both agents agree with no new question
direct answer is detected
LLM fails repeatedly
conversation stalls
blocked topic re-entry is detected
```

Stop reasons should be written explicitly into `relay_stop_reason`.

## Metrics

Compare A/B/C using the same observation windows.

Systems:

```text
A = Federation shared-workspace pair: char_001 + char_306
B = Federation relay pair: new NPC A + new NPC B
C = Genesis sim agents
```

Metrics:

```text
turns_to_resolution
artifact_count
direct_message_count
repeated_topic_count
fake_disagreement_count
stale_open_question_count
convergence_state_quality
blocked_topic_reentry_count
average_turn_length
resolution_summary_quality
human_readability_score
```

## Expected Signal

The relay pair should show:

```text
more direct replies
fewer artifacts during active dialogue
lower stale_open_question count
faster resolution
cleaner transcript
less inferred intent
```

The control pair should continue showing:

```text
productive shared-workspace drift
artifact-heavy collaboration
slower direct answer cycles
```

Genesis gives the third baseline for natural conversational behavior.

## Non-Goals

Stage 5A design does not include:

```text
no modification to char_001 or char_306
no new NPC creation yet
no Redis writes yet
no deployment yet
no restart yet
no implementation plan yet
```

## Verdict

Stage 5A should be tested on a fresh persistent pair. The existing councilor
pair remains the stabilized control group. The experiment tests whether exact
message forwarding creates more natural conversation than inferred dialogue
through shared Redis state.
