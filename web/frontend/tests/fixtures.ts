import type { Run, SessionSummary } from '../src/types';

export const SESSION_ID = '68df8b00aef4d8537282f001';

export const summary: SessionSummary = {
  session_id: SESSION_ID,
  schema_version: 1,
  started_at: '2026-10-01T09:07:04.000Z',
  received_at: '2026-10-01T09:07:05.123Z',
  status: 'IN_PROGRESS',
  completion_time: null,
  last_step_executed: [],
  execution_outcome: null,
};

export const run: Run = {
  run_id: '68df8b00aef4d8537282f002',
  session_id: SESSION_ID,
  schema_version: 1,
  step: 'pair-actions',
  command: 'actions-pairer',
  verdict: 'UNRECOGNIZED_VERDICT',
  occurred_at: '2026-10-01T09:17:58.000Z',
  received_at: '2026-10-01T09:17:59.456Z',
  details: {},
};

// Large numbers must enter the tests as JSON tokens, not rounded JS literals.
export const LARGE_DETAIL_JSON = `{
  "session_id": "${SESSION_ID}",
  "schema_version": 1,
  "started_at": "2026-10-01T09:07:04.000Z",
  "received_at": "2026-10-01T09:07:05.123Z",
  "status": "COMPLETED",
  "completion_time": null,
  "last_step_executed": ["pair-actions"],
  "execution_outcome": {
    "defect_count": 9223372036854775807,
    "gap_count": null,
    "extra": {"minimum": -9223372036854775808}
  },
  "metadata": {
    "recorded_by": {"name": "Agent"},
    "invoked_by": ["unverified", null],
    "literal": "$status",
    "operator": {"$set": {"x.y": 9007199254740993}},
    "__proto__": {"display_only": true},
    "_id": "nested-id",
    "html": "<script>alert(1)</script>"
  },
  "runs": [{
    "run_id": "68df8b00aef4d8537282f002",
    "session_id": "${SESSION_ID}",
    "schema_version": 1,
    "step": "pair-actions",
    "command": "actions-pairer",
    "verdict": "UNRECOGNIZED_VERDICT",
    "occurred_at": "2026-10-01T09:17:58.000Z",
    "received_at": "2026-10-01T09:17:59.456Z",
    "details": {"large": 9223372036854775807, "numeric_string": "9223372036854775807"}
  }]
}`;
