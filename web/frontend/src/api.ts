import { parseJson } from './json';
import { appendQueryParams } from './sessionQuery';
import { EXECUTION_OUTCOME_COUNT_FIELDS, NEWEST_SESSION_QUERY, SESSION_STATUSES } from './types';
import type {
  ApiErrorEnvelope,
  ApiFailure,
  ApiResult,
  ExecutionOutcome,
  JsonObject,
  JsonValue,
  Run,
  SessionDetail,
  SessionListRecord,
  SessionPage,
  SessionQuery,
  SessionSummary,
} from './types';

export function listSessions(signal?: AbortSignal): Promise<ApiResult<SessionPage<SessionSummary>>> {
  return getJson('/v1/sessions', acceptsSummaryPage, signal);
}

export function listSessionFields(
  fields: readonly string[],
  query: SessionQuery = NEWEST_SESSION_QUERY,
  signal?: AbortSignal,
): Promise<ApiResult<SessionPage<SessionListRecord>>> {
  const params = new URLSearchParams();
  const selected = fields.length === 0 ? ['session_id'] : [...new Set(fields)];
  for (const field of selected) params.append('fields', field);
  appendQueryParams(params, query);
  return getJson(`/v1/sessions?${params.toString()}`, acceptsProjectedPage, signal);
}

export function getSession(
  sessionId: string,
  signal?: AbortSignal,
): Promise<ApiResult<SessionDetail>> {
  return getJson(`/v1/sessions/${encodeURIComponent(sessionId)}`, isSessionDetail, signal);
}

async function getJson<T extends JsonValue>(
  path: string,
  accepts: (value: JsonValue) => value is T,
  signal?: AbortSignal,
): Promise<ApiResult<T>> {
  if (signal?.aborted) return cancelled();

  const options: RequestInit = {
    method: 'GET',
    headers: { Accept: 'application/json' },
    cache: 'no-store',
  };
  if (signal !== undefined) options.signal = signal;

  let response: Response;
  try {
    response = await fetch(path, options);
  } catch {
    // Only transport failures are caught here; decoding/programming errors are not.
    return signal?.aborted ? cancelled() : networkFailure();
  }
  if (signal?.aborted) return cancelled();

  const mediaType = response.headers.get('Content-Type')?.split(';')[0]?.trim().toLowerCase();
  if (mediaType !== 'application/json') {
    return response.ok
      ? invalidResponse(response.status)
      : failure({
          kind: 'http',
          status: response.status,
          message: 'The server could not complete the request.',
        });
  }

  let text: string;
  try {
    text = await response.text();
  } catch {
    return signal?.aborted ? cancelled() : networkFailure();
  }
  if (signal?.aborted) return cancelled();

  let body: JsonValue;
  try {
    body = parseJson(text);
  } catch (error) {
    if (error instanceof SyntaxError || error instanceof RangeError) {
      return invalidResponse(response.status);
    }
    throw error;
  }

  if (!response.ok) {
    if (!isErrorEnvelope(body)) return invalidResponse(response.status);
    return failure({
      kind: 'api',
      status: response.status,
      code: body.error.code,
      message: body.error.message,
    });
  }
  if (!accepts(body)) return invalidResponse(response.status);
  return { ok: true, data: body };
}

function failure(error: ApiFailure): ApiResult<never> {
  return { ok: false, error };
}

function cancelled(): ApiResult<never> {
  return failure({ kind: 'cancelled' });
}

function networkFailure(): ApiResult<never> {
  return failure({ kind: 'network', message: 'Unable to reach the server.' });
}

function invalidResponse(status: number): ApiResult<never> {
  return failure({
    kind: 'invalid_response',
    status,
    message: 'The server returned an invalid response.',
  });
}

// These guards inspect parsed JSON only. Extras stay opaque and are not rebuilt.
function isObject(value: JsonValue | undefined): value is JsonObject {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isId(value: JsonValue | undefined): value is string {
  return typeof value === 'string' && /^[0-9a-f]{24}$/.test(value);
}

function isTimestamp(value: JsonValue | undefined): value is string {
  // Check parseability before toISOString, which throws on out-of-range dates.
  return typeof value === 'string'
    && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/.test(value)
    && Number.isFinite(Date.parse(value))
    && new Date(value).toISOString() === value;
}

function isOutcome(value: JsonValue | undefined): value is ExecutionOutcome | null {
  if (value === null) return true;
  if (!isObject(value)) return false;
  return EXECUTION_OUTCOME_COUNT_FIELDS.every((key) => {
    const count = value[key];
    return count == null
      || (typeof count === 'number' && Number.isSafeInteger(count) && count >= 0)
      || (typeof count === 'bigint' && count >= 0n && count <= 9223372036854775807n);
  });
}

const sessionFieldChecks: Record<keyof SessionSummary, (value: JsonValue | undefined) => boolean> = {
  session_id: isId,
  schema_version: (value) => value === 1,
  started_at: isTimestamp,
  received_at: isTimestamp,
  status: (value) => SESSION_STATUSES.some((status) => status === value),
  completion_time: (value) => value === null || isTimestamp(value),
  last_step_executed: (value) => Array.isArray(value)
    && value.every((step) => typeof step === 'string'),
  execution_outcome: isOutcome,
};

function isSessionSummary(value: JsonValue): value is SessionSummary {
  return isObject(value) && Object.entries(sessionFieldChecks).every(
    ([field, accepts]) => Object.hasOwn(value, field) && accepts(value[field]),
  );
}

function isProjectedSession(value: JsonValue): value is SessionListRecord {
  return isObject(value)
    && Object.hasOwn(value, 'session_id') && isId(value.session_id)
    && Object.keys(value).every((field) => field === 'metadata' || Object.hasOwn(sessionFieldChecks, field))
    && (!Object.hasOwn(value, 'metadata') || isObject(value.metadata))
    && Object.entries(sessionFieldChecks).every(
      ([field, accepts]) => !Object.hasOwn(value, field) || accepts(value[field]),
    );
}

function isPageSize(value: JsonValue | undefined): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 1 && value <= 100;
}

function isTotalCount(value: JsonValue | undefined): boolean {
  return (typeof value === 'number' && Number.isSafeInteger(value) && value >= 0)
    || (typeof value === 'bigint' && value >= 0n);
}

function isCursor(value: JsonValue | undefined): boolean {
  return value === null || (typeof value === 'string' && value.length > 0);
}

// Every list response is the five-field page envelope, never a bare array.
function sessionPage<T extends JsonValue>(
  acceptsItem: (value: JsonValue) => value is T,
): (value: JsonValue) => value is SessionPage<T> {
  return (value): value is SessionPage<T> => isObject(value)
    && Object.keys(value).length === 5
    && Array.isArray(value.items) && value.items.every(acceptsItem)
    && isPageSize(value.page_size)
    && isTotalCount(value.total_count)
    && isCursor(value.next_cursor)
    && isCursor(value.previous_cursor);
}

const acceptsSummaryPage = sessionPage(isSessionSummary);
const acceptsProjectedPage = sessionPage(isProjectedSession);

function isRun(value: JsonValue): value is Run {
  return isObject(value)
    && isId(value.run_id)
    && isId(value.session_id)
    && value.schema_version === 1
    && typeof value.step === 'string'
    && typeof value.command === 'string'
    && typeof value.verdict === 'string'
    && isTimestamp(value.occurred_at)
    && isTimestamp(value.received_at)
    && isObject(value.details);
}

function isSessionDetail(value: JsonValue): value is SessionDetail {
  return isObject(value)
    && isObject(value.metadata)
    && Array.isArray(value.runs)
    && value.runs.every(isRun)
    && isSessionSummary(value);
}

function isErrorEnvelope(value: JsonValue): value is ApiErrorEnvelope {
  return isObject(value)
    && isObject(value.error)
    && typeof value.error.code === 'string'
    && value.error.code.length > 0
    && typeof value.error.message === 'string';
}
