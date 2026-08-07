# Capability request: test_cap

| Field | Value |
|-------|-------|
| Stage | review |
| Status | submitted |
| Requester | char_001 |
| Collaborator | char_306 |
| Capability key | `test_cap` |
| Priority | high |
| Agenda | agenda_ad35b16e8d361030 |
| Lifecycle version | 0 |

## Objective
Produce the capability-request producer bridge.

## Blocker
Test.

## Requested Change
Provide the structured capability 'test_cap' to support pair-level work.

## Attempts Already Made
Initial observation of repeated low-value turns due to missing workflow_visibility; seeking structured support through the pair agenda.

## Evidence
Test.

## Acceptance Criteria
The capability 'test_cap' is available to both councilors; decisions referencing it produce measurable progress; no repeated need filings occur.

## Expected Benefit
Improved coordination on agenda 'test_work_001' with reduced low-value turns.

## Implementation Risks
Requires shared agreement on scope; must not introduce fourth-wall artifacts.

## Raw JSON (collapsed)
```json
{
  "stable_id": "capreq_4ac6f36f66476281",
  "evidence": "Test.",
  "title": "Capability request: test_cap",
  "agenda_item_id": "agenda_ad35b16e8d361030",
  "updated_ts": "1786048757.683071",
  "capability_key": "test_cap",
  "objective": "Produce the capability-request producer bridge.",
  "revision_number": "0",
  "acceptance_test_result": "",
  "pair_slug": "char_001__char_306",
  "created_at": "2026-08-06T20:39:17.675826Z",
  "requested_change": "Provide the structured capability 'test_cap' to support pair-level work.",
  "delivery_reference": "",
  "request_id": "capreq_be4afd302ff5",
  "created_ts": "1786048757.6757774",
  "attempts": "Initial observation of repeated low-value turns due to missing workflow_visibility; seeking structured support through the pair agenda.",
  "collaborating_councilor_id": "char_306",
  "requester_id": "char_001",
  "implementation_risks": "Requires shared agreement on scope; must not introduce fourth-wall artifacts.",
  "acceptance_test_evidence": "",
  "updated_at": "2026-08-06T20:39:17.683068Z",
  "status": "submitted",
  "acceptance_criteria": "The capability 'test_cap' is available to both councilors; decisions referencing it produce measurable progress; no repeated need filings occur.",
  "transitions": [
    {
      "from": "draft",
      "to": "submitted",
      "actor": "char_001",
      "timestamp": "2026-08-06T20:39:17.683038Z",
      "reason": ""
    }
  ],
  "consulted_npcs": [
    "char_306"
  ],
  "priority": "high",
  "expected_benefit": "Improved coordination on agenda 'test_work_001' with reduced low-value turns.",
  "blocker": "Test."
}
```

## Architect Kilo command

Copy into the active tmux Kilo session:

```bash
# Process capability request capreq_be4afd302ff5
kilo run --session arch-loop --command /architect-entry \
  "process-request capreq_be4afd302ff5"
```