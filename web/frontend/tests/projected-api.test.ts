import { beforeEach, describe, expect, it, vi } from 'vitest';

import { getSession, listSessionFields, listSessions } from '../src/api';
import { SESSION_ID } from './fixtures';

const fetchMock = vi.fn<typeof fetch>();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal('fetch', fetchMock);
});

function respond(value: unknown, status = 200) {
  fetchMock.mockResolvedValue(new Response(JSON.stringify(value), {
    status, headers: { 'Content-Type': 'application/json' },
  }));
}

describe('projected session reads', () => {
  it('requests only repeated, deduplicated field paths and forwards cancellation', async () => {
    const controller = new AbortController();
    respond([{ session_id: SESSION_ID, metadata: { boundary: 'checkout' } }]);
    const fields = ['started_at', 'metadata.invoked_by.name', 'metadata.boundary', 'started_at'];
    expect((await listSessionFields(fields, controller.signal)).ok).toBe(true);
    expect(fetchMock.mock.calls[0]?.[0]).toBe('/v1/sessions?fields=started_at&fields=metadata.invoked_by.name&fields=metadata.boundary');
    expect(fetchMock.mock.calls[0]?.[1]?.signal).toBe(controller.signal);
    expect(fields).toHaveLength(4);
  });

  it('encodes unusual field names without introducing another query parameter', async () => {
    respond([]);
    await listSessionFields(['metadata.label & value']);
    expect(fetchMock.mock.calls[0]?.[0]).toBe('/v1/sessions?fields=metadata.label+%26+value');
  });

  it('requests ID-only records explicitly when there are no field dependencies', async () => {
    respond([{ session_id: SESSION_ID }]);
    expect(await listSessionFields([])).toEqual({ ok: true, data: [{ session_id: SESSION_ID }] });
    expect(fetchMock.mock.calls[0]?.[0]).toBe('/v1/sessions?fields=session_id');
  });

  it.each([
    [],
    [{ session_id: SESSION_ID }],
    [{ session_id: SESSION_ID, metadata: {} }],
    [{ session_id: SESSION_ID, metadata: { invoked_by: ['arbitrary'], boundary: null } }],
    [{ session_id: SESSION_ID, execution_outcome: null, completion_time: null }],
    [{ session_id: SESSION_ID, execution_outcome: { defect_count: 0, extra: { value: true } } }],
    [{ session_id: SESSION_ID, started_at: '2026-10-01T09:07:04.000Z', status: 'FAILED' }],
  ].map((records) => ({ records })))('preserves partial values without filling omitted fields: $records', async ({ records }) => {
    respond(records);
    expect(await listSessionFields(['metadata'])).toEqual({ ok: true, data: records });
  });

  it('retains exact int64 values inside projected outcomes and arbitrary metadata', async () => {
    fetchMock.mockResolvedValue(new Response(`[{"session_id":"${SESSION_ID}","execution_outcome":{"defect_count":9223372036854775807},"metadata":{"boundary":{"__proto__":-9223372036854775808}}}]`, {
      headers: { 'Content-Type': 'application/json' },
    }));
    const result = await listSessionFields(['execution_outcome.defect_count', 'metadata.boundary']);
    expect(result.ok).toBe(true);
    if (!result.ok) throw new Error('Expected a projected result.');
    expect(result.data[0]?.execution_outcome?.defect_count).toBe(9223372036854775807n);
    expect(result.data[0]?.metadata?.boundary).toHaveProperty('__proto__', -9223372036854775808n);
  });

  it.each([
    {}, null, [null], [{}], [{ session_id: 'bad-id' }],
    [{ session_id: SESSION_ID, runs: [] }],
    [{ session_id: SESSION_ID, metadata: null }],
    [{ session_id: SESSION_ID, metadata: [] }],
    [{ session_id: SESSION_ID, status: null }],
    [{ session_id: SESSION_ID, status: 'UNKNOWN' }],
    [{ session_id: SESSION_ID, started_at: null }],
    [{ session_id: SESSION_ID, started_at: '2026-13-01T00:00:00.000Z' }],
    [{ session_id: SESSION_ID, schema_version: '1' }],
    [{ session_id: SESSION_ID, last_step_executed: 'step' }],
    [{ session_id: SESSION_ID, execution_outcome: { gap_count: '0' } }],
    [{ session_id: SESSION_ID, invented_root: 'value' }],
  ].map((records) => ({ records })))('rejects invalid projected shapes and present fields: $records', async ({ records }) => {
    respond(records);
    expect(await listSessionFields(['metadata'])).toMatchObject({ ok: false, error: { kind: 'invalid_response' } });
  });

  it('does not weaken the original full-summary or full-detail decoders', async () => {
    respond([{ session_id: SESSION_ID }]);
    expect(await listSessions()).toMatchObject({ ok: false, error: { kind: 'invalid_response' } });
    respond({ session_id: SESSION_ID, metadata: {} });
    expect(await getSession(SESSION_ID)).toMatchObject({ ok: false, error: { kind: 'invalid_response' } });
  });

  it('preserves field-selection API errors without falling back to a broader request', async () => {
    respond({ error: { code: 'invalid_field', message: 'A request field is invalid.' } }, 400);
    expect(await listSessionFields(['metadata.$bad'])).toEqual({
      ok: false, error: { kind: 'api', status: 400, code: 'invalid_field', message: 'A request field is invalid.' },
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
