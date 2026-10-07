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

export type SessionListRecord = Pick<SessionSummary, 'session_id'>
  & Partial<Omit<SessionSummary, 'session_id'>>
  & { metadata?: JsonObject };

export type SessionFieldPath = keyof SessionSummary | 'metadata'
  | `metadata.${string}` | `execution_outcome.${string}`;

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

// Every list response is this envelope, with exactly these five fields.
export type SessionPage<T> = {
  items: T[];
  page_size: number;
  // Counts every filter match, independent of the cursor and the returned page.
  total_count: JsonNumber;
  next_cursor: string | null;
  previous_cursor: string | null;
};

export const SESSION_PAGE_SIZES = [25, 50, 100] as const;
export type SessionPageSize = (typeof SESSION_PAGE_SIZES)[number];
export const DEFAULT_SESSION_PAGE_SIZE: SessionPageSize = 25;

// Filter names are the API query parameter names. An empty value means absent.
export const SESSION_FILTER_NAMES = [
  'status', 'boundary', 'invoked_by_email', 'started_from', 'started_before',
] as const;
export type SessionFilterName = (typeof SESSION_FILTER_NAMES)[number];

// Applied filters. Timestamps are RFC 3339 UTC strings, as the API accepts them.
export type SessionFilters = Readonly<Record<SessionFilterName, string>>;

// Draft filters held by the form. Timestamps are local `datetime-local` values.
export type SessionFilterDraft = Readonly<Record<SessionFilterName, string>>;

export type SessionQuery = Readonly<{
  filters: SessionFilters;
  page_size: SessionPageSize;
  // Opaque continuation value from a previous response; empty means newest page.
  cursor: string;
}>;

export const EMPTY_SESSION_FILTERS: SessionFilters = {
  status: '', boundary: '', invoked_by_email: '', started_from: '', started_before: '',
};

export const NEWEST_SESSION_QUERY: SessionQuery = {
  filters: EMPTY_SESSION_FILTERS,
  page_size: DEFAULT_SESSION_PAGE_SIZE,
  cursor: '',
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
