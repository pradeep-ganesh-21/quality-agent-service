// bigint represents an integer JSON token that cannot fit safely in a number.
export type JsonNumber = number | bigint;
export type JsonValue = null | boolean | string | JsonNumber | JsonValue[] | JsonObject;
export type JsonObject = { [key: string]: JsonValue };

export const SESSION_STATUSES = ['IN_PROGRESS', 'COMPLETED', 'FAILED'] as const;
export type SessionStatus = (typeof SESSION_STATUSES)[number];

export const EXECUTION_OUTCOME_COUNT_FIELDS = [
  'defect_count', 'gap_count', 'contract_ingredient_count',
] as const;
export type ExecutionOutcome = JsonObject & Partial<Record<
  (typeof EXECUTION_OUTCOME_COUNT_FIELDS)[number], JsonNumber | null
>>;

export type SessionSummary = {
  session_id: string;
  schema_version: 1;
  started_at: string;
  received_at: string;
  status: SessionStatus;
  completion_time: string | null;
  last_step_executed: string[];
  execution_outcome: ExecutionOutcome | null;
};

export type Run = {
  run_id: string;
  session_id: string;
  schema_version: 1;
  step: string;
  command: string;
  verdict: string;
  occurred_at: string;
  received_at: string;
  details: JsonObject;
};

export type SessionDetail = SessionSummary & {
  metadata: JsonObject;
  runs: Run[];
};

export type ApiErrorEnvelope = {
  error: { code: string; message: string };
};

export type ApiFailure =
  | { kind: 'api'; status: number; code: string; message: string }
  | { kind: 'http'; status: number; message: string }
  | { kind: 'invalid_response'; status: number; message: string }
  | { kind: 'network'; message: string }
  | { kind: 'cancelled' };

export type ApiResult<T> =
  | { ok: true; data: T }
  | { ok: false; error: ApiFailure };
