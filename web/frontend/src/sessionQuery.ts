/** List query state: browser URL parsing, API serialization, and local time.
 *
 * Filter values are literal text for the API, never patterns. Timestamps travel
 * as RFC 3339 UTC and are converted to local wall-clock values only for display
 * and for the native date and time inputs.
 */
import { padNumber } from './format';
import {
  DEFAULT_SESSION_PAGE_SIZE,
  EMPTY_SESSION_FILTERS,
  SESSION_FILTER_NAMES,
  SESSION_PAGE_SIZES,
  SESSION_STATUSES,
} from './types';
import type {
  SessionFilterDraft,
  SessionFilterName,
  SessionFilters,
  SessionPageSize,
  SessionQuery,
} from './types';

const MAX_FILTER_TEXT_LENGTH = 256;

export const SESSION_FILTER_LABELS: Readonly<Record<SessionFilterName, string>> = {
  status: 'Status',
  boundary: 'Boundary',
  invoked_by_email: 'Invoked by email',
  started_from: 'Started from',
  started_before: 'Started before',
};

const TEXT_FILTERS = ['boundary', 'invoked_by_email'] as const;
const TIMESTAMP_FILTERS = ['started_from', 'started_before'] as const;
const QUERY_PARAMETERS: readonly string[] = [...SESSION_FILTER_NAMES, 'page_size', 'cursor'];

// Accepted API timestamp text: seconds are required and the zone is explicit.
const RFC_3339 = /^\d{4}-\d{2}-\d{2}[Tt](?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d+)?(?:[Zz]|[+-](?:[01]\d|2[0-3]):[0-5]\d)$/;
const UTC_INSTANT = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/;
// A native datetime-local value: seconds and milliseconds are optional.
const LOCAL_INPUT = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,3}))?)?$/;

export type LocalInputParse =
  | { ok: true; instant: string }
  | { ok: false; reason: 'invalid' | 'nonexistent' };

export type SessionQueryParse =
  | { ok: true; query: SessionQuery }
  | { ok: false; message: string };

export type SessionFiltersParse =
  | { ok: true; filters: SessionFilters }
  | { ok: false; message: string };

/** Render an API instant as the local wall-clock value a date input accepts. */
export function localInputFromInstant(instant: string): string {
  const date = new Date(instant);
  if (Number.isNaN(date.getTime())) return '';
  const calendar = `${padNumber(date.getFullYear(), 4)}-${padNumber(date.getMonth() + 1)}-${padNumber(date.getDate())}`;
  const clock = `${padNumber(date.getHours())}:${padNumber(date.getMinutes())}:${padNumber(date.getSeconds())}`;
  const milliseconds = date.getMilliseconds();
  return milliseconds === 0
    ? `${calendar}T${clock}`
    : `${calendar}T${clock}.${padNumber(milliseconds, 3)}`;
}

/** Resolve a local wall-clock value to the UTC instant the API expects. */
export function instantFromLocalInput(value: string): LocalInputParse {
  const match = LOCAL_INPUT.exec(value);
  if (match === null) return { ok: false, reason: 'invalid' };
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const hours = Number(match[4]);
  const minutes = Number(match[5]);
  const seconds = Number(match[6] ?? '0');
  const milliseconds = Number((match[7] ?? '').padEnd(3, '0'));

  const date = new Date(year, month - 1, day, hours, minutes, seconds, milliseconds);
  if (Number.isNaN(date.getTime())) return { ok: false, reason: 'invalid' };
  // An impossible calendar date rolls over while keeping its time of day.
  if (date.getFullYear() !== year || date.getMonth() !== month - 1 || date.getDate() !== day) {
    return { ok: false, reason: 'invalid' };
  }
  // A shifted time of day means this local time is skipped by a clock change.
  if (date.getHours() !== hours || date.getMinutes() !== minutes
    || date.getSeconds() !== seconds || date.getMilliseconds() !== milliseconds) {
    return { ok: false, reason: 'nonexistent' };
  }

  const instant = date.toISOString();
  return UTC_INSTANT.test(instant) ? { ok: true, instant } : { ok: false, reason: 'invalid' };
}

export function activeFilterCount(filters: SessionFilters): number {
  return SESSION_FILTER_NAMES.filter((name) => filters[name] !== '').length;
}

function textLengthProblem(value: string, label: string): string | null {
  if (value.includes('\u0000')) return `${label} contains an unsupported character.`;
  // The API bounds filter text by characters, so count code points.
  if ([...value].length > MAX_FILTER_TEXT_LENGTH) {
    return `${label} must be ${MAX_FILTER_TEXT_LENGTH} characters or fewer.`;
  }
  return null;
}

function isKnownStatus(value: string): boolean {
  return SESSION_STATUSES.some((status) => status === value);
}

function normalizeInstant(value: string): string | null {
  if (!RFC_3339.test(value)) return null;
  const time = Date.parse(value);
  if (!Number.isFinite(time)) return null;
  const instant = new Date(time).toISOString();
  return UTC_INSTANT.test(instant) ? instant : null;
}

function rangeProblem(filters: Record<SessionFilterName, string>): string | null {
  const { started_from: from, started_before: before } = filters;
  if (from === '' || before === '') return null;
  return Date.parse(from) < Date.parse(before)
    ? null
    : `${SESSION_FILTER_LABELS.started_from} must be earlier than ${SESSION_FILTER_LABELS.started_before.toLowerCase()}.`;
}

/** Validate the browser URL into applied list state, without widening it. */
export function parseSessionQuery(search: URLSearchParams): SessionQueryParse {
  const supplied = new Map<string, string>();
  for (const [name, value] of search) {
    // An unknown or repeated parameter is rejected rather than ignored, so a
    // hand-edited link cannot silently show a wider result set.
    if (!QUERY_PARAMETERS.includes(name)) {
      return { ok: false, message: 'This link uses a filter this page does not support.' };
    }
    if (supplied.has(name)) {
      return { ok: false, message: 'This link repeats a filter.' };
    }
    if (value === '') {
      return { ok: false, message: 'This link contains an empty filter value.' };
    }
    supplied.set(name, value);
  }

  let pageSize: SessionPageSize = DEFAULT_SESSION_PAGE_SIZE;
  const suppliedPageSize = supplied.get('page_size');
  if (suppliedPageSize !== undefined) {
    const known = SESSION_PAGE_SIZES.find((size) => size.toString() === suppliedPageSize);
    if (known === undefined) {
      return { ok: false, message: 'This link uses a page size this page does not offer.' };
    }
    pageSize = known;
  }

  const filters: Record<SessionFilterName, string> = { ...EMPTY_SESSION_FILTERS };

  const status = supplied.get('status');
  if (status !== undefined) {
    if (!isKnownStatus(status)) {
      return { ok: false, message: 'This link uses an unknown status filter.' };
    }
    filters.status = status;
  }

  for (const name of TEXT_FILTERS) {
    const value = supplied.get(name);
    if (value === undefined) continue;
    const problem = textLengthProblem(value, SESSION_FILTER_LABELS[name]);
    if (problem !== null) return { ok: false, message: problem };
    filters[name] = value;
  }

  for (const name of TIMESTAMP_FILTERS) {
    const value = supplied.get(name);
    if (value === undefined) continue;
    const instant = normalizeInstant(value);
    if (instant === null) {
      return { ok: false, message: `${SESSION_FILTER_LABELS[name]} is not a valid date and time.` };
    }
    filters[name] = instant;
  }

  const problem = rangeProblem(filters);
  if (problem !== null) return { ok: false, message: problem };

  return {
    ok: true,
    query: { filters, page_size: pageSize, cursor: supplied.get('cursor') ?? '' },
  };
}

function appendFilters(params: URLSearchParams, filters: SessionFilters): void {
  // Each parameter is appended at most once, and an absent filter is omitted
  // entirely: the API rejects an empty filter value.
  for (const name of SESSION_FILTER_NAMES) {
    const value = filters[name];
    if (value !== '') params.append(name, value);
  }
}

/** Serialize applied state for the browser URL. */
export function toSearchParams(query: SessionQuery): URLSearchParams {
  const params = new URLSearchParams();
  appendFilters(params, query.filters);
  // The default page size is the API default too, so a plain link omits it.
  if (query.page_size !== DEFAULT_SESSION_PAGE_SIZE) {
    params.append('page_size', query.page_size.toString());
  }
  if (query.cursor !== '') params.append('cursor', query.cursor);
  return params;
}

/** Add filters, the effective page size, and any cursor to an API request. */
export function appendQueryParams(params: URLSearchParams, query: SessionQuery): void {
  appendFilters(params, query.filters);
  params.append('page_size', query.page_size.toString());
  if (query.cursor !== '') params.append('cursor', query.cursor);
}

/** Seed the form inputs from applied state. */
export function draftFromFilters(filters: SessionFilters): SessionFilterDraft {
  return {
    ...filters,
    started_from: filters.started_from === '' ? '' : localInputFromInstant(filters.started_from),
    started_before: filters.started_before === '' ? '' : localInputFromInstant(filters.started_before),
  };
}

/**
 * Validate submitted form inputs into applied filters.
 *
 * An unedited date input keeps the exact applied instant, so re-applying a
 * restored link cannot shift it by the precision the input cannot show.
 */
export function filtersFromDraft(
  draft: SessionFilterDraft,
  applied: SessionFilters,
): SessionFiltersParse {
  const filters: Record<SessionFilterName, string> = { ...EMPTY_SESSION_FILTERS };

  if (draft.status !== '') {
    if (!isKnownStatus(draft.status)) {
      return { ok: false, message: `${SESSION_FILTER_LABELS.status} is not a known value.` };
    }
    filters.status = draft.status;
  }

  for (const name of TEXT_FILTERS) {
    const value = draft[name];
    // Blank and whitespace-only text is no filter at all. Any other value is
    // kept verbatim, because the API matches it literally.
    if (value.trim() === '') continue;
    const problem = textLengthProblem(value, SESSION_FILTER_LABELS[name]);
    if (problem !== null) return { ok: false, message: problem };
    filters[name] = value;
  }

  for (const name of TIMESTAMP_FILTERS) {
    const value = draft[name];
    if (value === '') continue;
    const appliedInstant = applied[name];
    if (appliedInstant !== '' && value === localInputFromInstant(appliedInstant)) {
      filters[name] = appliedInstant;
      continue;
    }
    const parsed = instantFromLocalInput(value);
    if (!parsed.ok) {
      return {
        ok: false,
        message: parsed.reason === 'nonexistent'
          ? `${SESSION_FILTER_LABELS[name]} does not exist in this time zone.`
          : `${SESSION_FILTER_LABELS[name]} needs a complete date and time.`,
      };
    }
    filters[name] = parsed.instant;
  }

  const problem = rangeProblem(filters);
  if (problem !== null) return { ok: false, message: problem };

  return { ok: true, filters };
}
