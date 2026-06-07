# Context Pack: P002

## Project
Federation = consciousness simulation. Single HTML + vanilla JS frontend, FastAPI backend, Docker on VPS.

## Mode Assignment
- **Plan mode**: GLM 5.1
- **Build mode**: Nemotron 3 Ultra

## Current State
HEAD=1c04c40. P001 bridge system complete. Backend issues choice_token via `_issue_choice_token()` in events.py:48. `/choose` in core.py:252 accepts optional `?choice_token=` param. **Frontend has ZERO token integration** — sends bare /choose requests.

## Key Constraints
- Backend single-worker enforced
- `/choose` must always return `"outcome"` key
- No backend changes, no VPS deploy in P002
- adult.js IS production (served at federation-game.deliberatefederation.cloud/adult.html)

## Code Pattern (all 3 files)
```js
// Module-level (after existing vars)
let currentChoiceToken = null;

// In /event handler
currentChoiceToken = data.choice_token || null;

// In /choose URL
const url = `/choose?choice_token=${currentChoiceToken || ''}`;

// In error recovery
if (err.includes('choice token')) { currentChoiceToken = null; fetchEvent(); }
```

## File Targets
- index.js: store@168, URL@179
- bridge.js: store@790, URL@855
- adult.js: store@221, URL@229

## Token Budget
<2000 tokens ✅