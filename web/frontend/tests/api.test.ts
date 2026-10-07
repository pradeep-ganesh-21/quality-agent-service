import { beforeEach, describe, expect, it, vi } from 'vitest';

import { getSession, listSessions } from '../src/api';
import { stringifyJson } from '../src/json';
import type { JsonValue } from '../src/types';
import { LARGE_DETAIL_JSON, page, run, SESSION_ID, summary } from './fixtures';

const fetchMock = vi.fn<typeof fetch>();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal('fetch', fetchMock);
});

function respond(value: JsonValue, status = 200): void {
  respondWithText(stringifyJson(value), status);
}

function respondWithText(text: string, status = 200): void {
  fetchMock.mockResolvedValue(new Response(text, {
    status,
    headers: { 'Content-Type': 'application/json' },
  }));
}

describe('session reads', () => {
  it('uses the exact default list URL and GET without retries or an upstream URL', async () => {
    respond(page([summary]));
    expect(await listSessions()).toEqual({ ok: true, data: page([summary]) });
    expect(fetchMock).toHaveBeenCalledExactlyOnceWith('/v1/sessions', {
      method: 'GET',
      headers: { Accept: 'application/json' },
      cache: 'no-store',
    });
  });

  it('accepts an empty page and reports the live match count', async () => {
    respond(page([], { total_count: 318, next_cursor: null, previous_cursor: 'djF8cHJldg' }));
    expect(await listSessions()).toEqual({
      ok: true,
      data: page([], { total_count: 318, previous_cursor: 'djF8cHJldg' }),
    });
  });

  it('returns every session in backend order', async () => {
    const values = Array.from({ length: 1101 }, (_, index) => ({
      ...summary,
      session_id: index.toString(16).padStart(24, '0'),
    }));
    respond(page(values, { page_size: 100, total_count: 9007199254740991 }));
    expect(await listSessions()).toEqual({
      ok: true,
      data: page(values, { page_size: 100, total_count: 9007199254740991 }),
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('encodes the detail ID as one path segment, without interpreting it as a URL', async () => {
    const id = 'folder/id ?#%日本語';
    respond({ error: { code: 'session_not_found', message: 'Session not found.' } }, 404);
    await getSession(id);
    expect(fetchMock.mock.calls[0]?.[0]).toBe('/v1/sessions/folder%2Fid%20%3F%23%25%E6%97%A5%E6%9C%AC%E8%AA%9E');
  });

  it('fetches detail with an empty run list and absent identities', async () => {
    const detail = { ...summary, metadata: {}, runs: [] };
    respond(detail);
    expect(await getSession(SESSION_ID)).toEqual({ ok: true, data: detail });
    expect(fetchMock.mock.calls[0]?.[0]).toBe(`/v1/sessions/${SESSION_ID}`);
  });

  it('preserves exact counts, identity values, metadata, run details, and unknown verdicts', async () => {
    respondWithText(LARGE_DETAIL_JSON);
    const result = await getSession(SESSION_ID);
    expect(result.ok).toBe(true);
    if (!result.ok) throw new Error('Expected a successful detail response.');

    expect(result.data.execution_outcome).toEqual({
      defect_count: 9223372036854775807n,
      gap_count: null,
      extra: { minimum: -9223372036854775808n },
    });
    expect(result.data.execution_outcome).not.toHaveProperty('contract_ingredient_count');
    expect(result.data.last_step_executed).toEqual(['pair-actions']);
    expect(result.data.metadata).toMatchObject({
      recorded_by: { name: 'Agent' },
      invoked_by: ['unverified', null],
      literal: '$status',
      operator: { $set: { 'x.y': 9007199254740993n } },
      _id: 'nested-id',
      html: '<script>alert(1)</script>',
    });
    expect(Object.hasOwn(result.data.metadata, '__proto__')).toBe(true);
    expect(result.data.runs[0]?.verdict).toBe('UNRECOGNIZED_VERDICT');
    expect(result.data.runs[0]?.details).toEqual({
      large: 9223372036854775807n,
      numeric_string: '9223372036854775807',
    });
  });

  it('does not reorder runs or calculate an execution outcome', async () => {
    const detail = {
      ...summary,
      metadata: {},
      runs: [run, { ...run, run_id: '68df8b00aef4d8537282f003', occurred_at: summary.started_at }],
    };
    respond(detail);
    expect(await getSession(SESSION_ID)).toEqual({ ok: true, data: detail });
  });

  it('accepts media type parameters and case differences', async () => {
    fetchMock.mockResolvedValue(new Response(stringifyJson(page([])), {
      headers: { 'Content-Type': 'Application/JSON; charset=utf-8' },
    }));
    expect(await listSessions()).toEqual({ ok: true, data: page([]) });
  });

  it.each([null, {}, { gap_count: null }, { defect_count: 0 }, { extra: { arbitrary: true } }])(
    'preserves unknown, missing, and zero outcome counts: %j',
    async (execution_outcome) => {
      const value = { ...summary, execution_outcome };
      respond(page([value]));
      expect(await listSessions()).toEqual({ ok: true, data: page([value]) });
    },
  );
});

describe('HTTP and response failures', () => {
  it.each([404, 500])('preserves the API code and message on HTTP %s', async (status) => {
    const error = { code: 'future_error_code', message: 'A safe API message.' };
    respond({ error }, status);
    expect(await listSessions()).toEqual({ ok: false, error: { kind: 'api', status, ...error } });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('does not let extra error fields override the HTTP status or failure kind', async () => {
    respond({ error: { code: 'session_not_found', message: 'Session not found.', kind: 'cancelled', status: 200 } }, 404);
    expect(await listSessions()).toEqual({
      ok: false,
      error: { kind: 'api', status: 404, code: 'session_not_found', message: 'Session not found.' },
    });
  });

  it.each([502, 504])('does not read or expose an HTML HTTP %s body', async (status) => {
    const response = new Response('<html>private upstream error</html>', {
      status,
      headers: { 'Content-Type': 'text/html' },
    });
    const readBody = vi.spyOn(response, 'text');
    fetchMock.mockResolvedValue(response);
    expect(await listSessions()).toEqual({
      ok: false,
      error: { kind: 'http', status, message: 'The server could not complete the request.' },
    });
    expect(readBody).not.toHaveBeenCalled();
  });

  it.each(['text/html', 'text/plain', 'application/jsonp', ''])('rejects a non-JSON success with content type %s', async (mediaType) => {
    fetchMock.mockResolvedValue(new Response(stringifyJson(page([])), { headers: { 'Content-Type': mediaType } }));
    expect(await listSessions()).toEqual({
      ok: false,
      error: { kind: 'invalid_response', status: 200, message: 'The server returned an invalid response.' },
    });
  });

  it('rejects a response without Content-Type', async () => {
    fetchMock.mockResolvedValue(new Response());
    expect(await listSessions()).toMatchObject({ ok: false, error: { kind: 'invalid_response' } });
  });

  it.each(['{private text', '<html>private text</html>', '', '[1,]', '[1e999]'])(
    'sanitizes invalid JSON advertised as JSON: %s',
    async (text) => {
      respondWithText(text);
      expect(await listSessions()).toEqual({
        ok: false,
        error: { kind: 'invalid_response', status: 200, message: 'The server returned an invalid response.' },
      });
    },
  );

  it.each([{}, { error: 'oops' }, { error: { code: 2, message: 'oops' } }, { error: { code: '', message: 'oops' } }, { error: { code: 'x' } }])(
    'rejects malformed API error envelopes: %j',
    async (value) => {
      respond(value, 500);
      expect(await listSessions()).toMatchObject({ ok: false, error: { kind: 'invalid_response', status: 500 } });
    },
  );

  it.each([
    null,
    {},
    [summary],
    page([summary, null]),
    page([1]),
    { ...page([summary]), extra: true },
    { items: [summary], page_size: 25, total_count: 1, next_cursor: null },
    page([summary], { page_size: 0 }),
    page([summary], { page_size: 101 }),
    page([summary], { page_size: 25.5 }),
    page([summary], { total_count: -1 }),
    page([summary], { total_count: 1.5 }),
    page([summary], { next_cursor: '' }),
    page([summary], { previous_cursor: 7 as unknown as string }),
  ])('rejects a non-envelope or invalid page: %j', async (value) => {
    respond(value as JsonValue);
    expect(await listSessions()).toMatchObject({ ok: false, error: { kind: 'invalid_response' } });
  });

  it.each(Object.keys(summary))('requires summary field %s', async (missing) => {
    const value = Object.fromEntries(Object.entries(summary).filter(([key]) => key !== missing));
    respondWithText(JSON.stringify(page([value])));
    expect(await listSessions()).toMatchObject({ ok: false, error: { kind: 'invalid_response' } });
  });

  it.each([
    { field: 'session_id', value: 'not-an-id' },
    { field: 'schema_version', value: '1' },
    { field: 'schema_version', value: 2 },
    { field: 'started_at', value: '2026-02-30T09:07:04.000Z' },
    { field: 'started_at', value: '2026-13-01T00:00:00.000Z' },
    { field: 'started_at', value: '2026-10-32T00:00:00.000Z' },
    { field: 'started_at', value: '2026-10-01T25:00:00.000Z' },
    { field: 'received_at', value: '2026-10-01T09:07:04' },
    { field: 'completion_time', value: 0 },
    { field: 'status', value: 'UNKNOWN' },
    { field: 'last_step_executed', value: ['step', 1] },
    { field: 'execution_outcome', value: [] },
    { field: 'execution_outcome', value: { defect_count: '0' } },
    { field: 'execution_outcome', value: { defect_count: false } },
    { field: 'execution_outcome', value: { defect_count: -1 } },
    { field: 'execution_outcome', value: { defect_count: 1.5 } },
    { field: 'execution_outcome', value: { defect_count: 9223372036854775808n } },
  ])('rejects an invalid $field without coercion', async ({ field, value }) => {
    respond(page([{ ...summary, [field]: value }]));
    expect(await listSessions()).toMatchObject({ ok: false, error: { kind: 'invalid_response' } });
  });

  it.each([
    { ...summary, runs: [] },
    { ...summary, metadata: {} },
    { ...summary, metadata: null, runs: [] },
    { ...summary, metadata: {}, runs: [null] },
    { ...summary, metadata: {}, runs: [{ ...run, details: null }] },
    { ...summary, metadata: {}, runs: [{ ...run, verdict: 0 }] },
    { ...summary, metadata: {}, runs: [{ ...run, occurred_at: 'yesterday' }] },
    { ...summary, metadata: {}, runs: [{ ...run, occurred_at: '2026-13-01T00:00:00.000Z' }] },
  ])('rejects malformed detail or run fields', async (value) => {
    respond(value);
    expect(await getSession(SESSION_ID)).toMatchObject({ ok: false, error: { kind: 'invalid_response' } });
  });
});

describe('transport and cancellation', () => {
  it('sanitizes network failure without retrying', async () => {
    fetchMock.mockRejectedValue(new TypeError('private connection details'));
    expect(await listSessions()).toEqual({ ok: false, error: { kind: 'network', message: 'Unable to reach the server.' } });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('handles a connection lost while reading the body', async () => {
    const response = new Response('', { headers: { 'Content-Type': 'application/json' } });
    vi.spyOn(response, 'text').mockRejectedValue(new TypeError('private stream details'));
    fetchMock.mockResolvedValue(response);
    expect(await listSessions()).toMatchObject({ ok: false, error: { kind: 'network' } });
  });

  it('does not fetch when the caller has already cancelled', async () => {
    const controller = new AbortController();
    controller.abort();
    expect(await listSessions(controller.signal)).toEqual({ ok: false, error: { kind: 'cancelled' } });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('passes the caller signal and distinguishes in-flight cancellation from network failure', async () => {
    const controller = new AbortController();
    fetchMock.mockImplementation((_url, options) => new Promise((_resolve, reject) => {
      options?.signal?.addEventListener('abort', () => reject(controller.signal.reason));
    }));
    const pending = getSession(SESSION_ID, controller.signal);
    controller.abort();
    expect(await pending).toEqual({ ok: false, error: { kind: 'cancelled' } });
    expect(fetchMock.mock.calls[0]?.[1]?.signal).toBe(controller.signal);
  });

  it('returns cancellation if the body read is aborted', async () => {
    const controller = new AbortController();
    const response = new Response('', { headers: { 'Content-Type': 'application/json' } });
    vi.spyOn(response, 'text').mockImplementation(async () => {
      controller.abort();
      throw controller.signal.reason;
    });
    fetchMock.mockResolvedValue(response);
    expect(await listSessions(controller.signal)).toEqual({ ok: false, error: { kind: 'cancelled' } });
  });

  it('does not return late success after cancellation', async () => {
    const controller = new AbortController();
    const response = new Response('', { headers: { 'Content-Type': 'application/json' } });
    vi.spyOn(response, 'text').mockImplementation(async () => {
      controller.abort();
      return stringifyJson(page([]));
    });
    fetchMock.mockResolvedValue(response);
    expect(await listSessions(controller.signal)).toEqual({ ok: false, error: { kind: 'cancelled' } });
  });
});
