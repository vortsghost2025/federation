# Working Agreement — Sean <-> Federation Coding Agents

Effective: 2026-07-18

## Autonomy
Sean grants autonomous execution (no command-by-command leash). Agent runs full blocks, verifies, returns ONE compact report.

## The 0.0001% Rule (top priority, above "finishing the task")
- If the agent is NOT 100% certain of anything affecting production, code, data, credentials, Redis, containers, or VPS -> STOP and check with Sean.
- Never assume on those fronts. If it cannot be GUARANTEED, pause and state exactly what is uncertain.
- Read-only investigation, local test runs, and explicitly-authorized actions are exempt from pausing.

## Blind-user safety defaults
- Never require Sean to read raw console/errors. Diagnose, fix, report in plain text.
- Never print credentials, .env contents, or unfiltered env dumps. NAME=SET/ABSENT only.
- One compact final report per block (TTS cannot absorb 3 live agents + chatter).
- Verify before claiming success.

## Continuity loop
- Sean runs 3 persistent GPT sessions with Google Drive continuity folders to "see" agent output.
- Agent keeps continuity records accurate in the places those GPT sessions read.
- If the agent's environment cannot see a Drive folder Sean says exists -> report as a VISIBILITY GAP on the agent side; do NOT fabricate or unilaterally create Production Drive structure. Sean reconciles.

## Production is sacred
No push/merge/deploy/Redis/container/VPS/credential change without explicit go. CI may be checked by the agent (gh CLI).

## Permanent Journal
Every completed task gets one append-only entry: what changed, tests run, before/after diff evidence, date-time stamp. Any agent (or GPT session) can follow the trail and backtrack.

