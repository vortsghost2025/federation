# G6 Shadow Salvage Recovery Report

Generated UTC: 2026-07-20T22:18:48Z

## Recovery status

- Verdict: WATCH
- Branch: salvage/g6-shadow-qualification-20260720-recovered
- Base: origin/npc-topic-loop-control
- Recovered test: federation-game/npc-agent-shadow/test_npc_g6_behavioral.py
- Copilot's earlier claimed salvage commit and remote push were not found.
- The corrected test was recovered from an ignored local worktree file.

## Isolation and safety

- Protected persistent councilor identifiers are absent from the recovered test.
- Synthetic test identities: test_char_901 and test_char_902
- Shadow mode enabled.
- Redis URL empty.
- No live Redis access.
- No VPS access.
- No Postgres access.
- No Docker access.
- No production deployment.
- No paid model access.
- No production backend source files edited.
- No old absolute Copilot worktree path remains in the recovered test.

## Verification

- Python parse: PASS
- Tests collected: 18
- Tests passed: 11
- Tests failed: 7
- Tests timed out: 0
- Full-suite runtime: 0.44 seconds

## Remaining failures

1. Artifact-topic streak test passes a non-hex prompt hash to code expecting hexadecimal input.
2. Artifact deduplication tests expect live action results while shadow mode correctly returns shadow_intent_only.
3. Institution similar-name test expects live creation/blocking behavior while shadow mode records intent only.
4. Realistic arc test expects live action results while shadow mode records intent only.
5. Provider-call limit expectation does not match the configured 200-call shadow limit.
6. Sustained-call test expects intents in a Redis location not populated by the current isolated fixture.

## Interpretation

This commit preserves recovered G6 test work as isolated WIP evidence.

It does not claim full G6 qualification.
It does not authorize production use.
It does not authorize deployment.
It does not authorize testing on protected persistent councilors.
It must not be merged until the seven remaining behavioral and fixture
mismatches are reviewed and resolved.