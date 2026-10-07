import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import {
  activeFilterCount,
  appendQueryParams,
  draftFromFilters,
  filtersFromDraft,
  instantFromLocalInput,
  localInputFromInstant,
  parseSessionQuery,
  toSearchParams,
} from '../src/sessionQuery';
import { EMPTY_SESSION_FILTERS, NEWEST_SESSION_QUERY } from '../src/types';
import type { SessionFilterDraft, SessionFilters } from '../src/types';

function filters(values: Partial<SessionFilters> = {}): SessionFilters {
  return { ...EMPTY_SESSION_FILTERS, ...values };
}

function draft(values: Partial<SessionFilterDraft> = {}): SessionFilterDraft {
  return { ...EMPTY_SESSION_FILTERS, ...values };
}

function parse(search: string) {
  return parseSessionQuery(new URLSearchParams(search));
}

describe('local time conversion', () => {
  it('runs in the pinned test time zone', () => {
    expect(new Date('2026-10-01T00:00:00.000Z').getTimezoneOffset()).toBe(-330);
  });

  it.each([
    ['2026-10-01T09:07', '2026-10-01T03:37:00.000Z'],
    ['2026-10-01T09:07:04', '2026-10-01T03:37:04.000Z'],
    ['2026-10-01T09:07:04.123', '2026-10-01T03:37:04.123Z'],
    ['2026-10-01T09:07:04.1', '2026-10-01T03:37:04.100Z'],
    ['2026-01-01T00:00', '2025-12-31T18:30:00.000Z'],
  ])('converts the local value %s to %s', (value, expected) => {
    expect(instantFromLocalInput(value)).toEqual({ ok: true, instant: expected });
  });

  it.each([
    '', '2026-10-01', '09:07', '2026-10-01 09:07', '2026-10-01T09:07:04.000Z',
    '2026-13-01T09:07', '2026-02-30T09:07', '2026-10-01T24:00', '0000-01-01T00:00',
  ])('rejects the unusable local value %s', (value) => {
    expect(instantFromLocalInput(value)).toEqual({ ok: false, reason: 'invalid' });
  });

  it.each([
    ['2026-10-01T03:37:00.000Z', '2026-10-01T09:07:00'],
    ['2026-10-01T03:37:04.000Z', '2026-10-01T09:07:04'],
    ['2026-10-01T03:37:04.123Z', '2026-10-01T09:07:04.123'],
  ])('renders the instant %s as the local input value %s', (instant, expected) => {
    expect(localInputFromInstant(instant)).toBe(expected);
  });

  it('round-trips an instant through the input value without drift', () => {
    const instant = '2026-10-01T03:37:04.123Z';
    expect(instantFromLocalInput(localInputFromInstant(instant))).toEqual({ ok: true, instant });
  });
});

describe('local time conversion across a daylight saving change', () => {
  const zone = process.env.TZ;

  beforeAll(() => { process.env.TZ = 'America/New_York'; });
  afterAll(() => { process.env.TZ = zone; });

  it('applies the switched zone', () => {
    expect(new Date('2026-07-01T00:00:00.000Z').getTimezoneOffset()).toBe(240);
  });

  it('rejects a local time that the spring clock change skips', () => {
    expect(instantFromLocalInput('2026-03-08T02:30')).toEqual({ ok: false, reason: 'nonexistent' });
  });

  it('accepts a repeated autumn local time and resolves it to the earlier offset', () => {
    expect(instantFromLocalInput('2026-11-01T01:30')).toEqual({ ok: true, instant: '2026-11-01T05:30:00.000Z' });
  });

  it.each(['2026-03-08T01:59:59', '2026-03-08T03:00'])('accepts %s on either side of the gap', (value) => {
    expect(instantFromLocalInput(value).ok).toBe(true);
  });
});

describe('parseSessionQuery', () => {
  it('reads an empty search as the newest default page', () => {
    expect(parse('')).toEqual({ ok: true, query: NEWEST_SESSION_QUERY });
  });

  it('reads every supported parameter', () => {
    expect(parse(
      'status=COMPLETED&boundary=check.out&invoked_by_email=Operator%40Example.invalid'
      + '&started_from=2026-10-01T03:37:00.000Z&started_before=2026-10-02T03:37:00.000Z'
      + '&page_size=100&cursor=djF8bmV4dHwx',
    )).toEqual({
      ok: true,
      query: {
        filters: filters({
          status: 'COMPLETED',
          boundary: 'check.out',
          invoked_by_email: 'Operator@Example.invalid',
          started_from: '2026-10-01T03:37:00.000Z',
          started_before: '2026-10-02T03:37:00.000Z',
        }),
        page_size: 100,
        cursor: 'djF8bmV4dHwx',
      },
    });
  });

  it.each([
    ['2026-10-01T09:07:04+05:30', '2026-10-01T03:37:04.000Z'],
    ['2026-10-01T03:37:04.1234Z', '2026-10-01T03:37:04.123Z'],
    ['2026-10-01t03:37:04z', '2026-10-01T03:37:04.000Z'],
  ])('normalizes the supplied bound %s to %s without shifting the instant', (value, expected) => {
    const result = parse(`started_from=${encodeURIComponent(value)}`);
    expect(result.ok && result.query.filters.started_from).toBe(expected);
  });

  it.each([
    ['sort=started_at', 'This link uses a filter this page does not support.'],
    ['fields=status', 'This link uses a filter this page does not support.'],
    ['status=COMPLETED&status=FAILED', 'This link repeats a filter.'],
    ['status=', 'This link contains an empty filter value.'],
    ['boundary=', 'This link contains an empty filter value.'],
    ['page_size=10', 'This link uses a page size this page does not offer.'],
    ['page_size=025', 'This link uses a page size this page does not offer.'],
    ['page_size=0', 'This link uses a page size this page does not offer.'],
    ['status=DONE', 'This link uses an unknown status filter.'],
    ['status=completed', 'This link uses an unknown status filter.'],
    ['started_from=yesterday', 'Started from is not a valid date and time.'],
    ['started_from=2026-10-01T09:07:04', 'Started from is not a valid date and time.'],
    ['started_from=2026-13-01T00:00:00Z', 'Started from is not a valid date and time.'],
    ['started_before=2026-10-01T09:07Z', 'Started before is not a valid date and time.'],
  ])('rejects the link %s', (search, message) => {
    expect(parse(search)).toEqual({ ok: false, message });
  });

  it.each([
    'started_from=2026-10-02T00:00:00Z&started_before=2026-10-01T00:00:00Z',
    'started_from=2026-10-01T00:00:00Z&started_before=2026-10-01T00:00:00Z',
  ])('rejects the inverted or empty range %s', (search) => {
    expect(parse(search)).toEqual({ ok: false, message: 'Started from must be earlier than started before.' });
  });

  it('rejects filter text that is too long or holds NUL, counting characters not code units', () => {
    const astral = '\u{1F600}'.repeat(256);
    expect(parse(`boundary=${encodeURIComponent(astral)}`).ok).toBe(true);
    expect(parse(`boundary=${encodeURIComponent(astral + 'a')}`)).toEqual({
      ok: false, message: 'Boundary must be 256 characters or fewer.',
    });
    expect(parse('invoked_by_email=a%00b')).toEqual({
      ok: false, message: 'Invoked by email contains an unsupported character.',
    });
  });

  it('keeps a cursor opaque for the API to validate', () => {
    const result = parse('cursor=not-base64!!');
    expect(result.ok && result.query.cursor).toBe('not-base64!!');
  });
});

describe('query serialization', () => {
  it('omits absent filters and the default page size from the browser URL', () => {
    expect(toSearchParams(NEWEST_SESSION_QUERY).toString()).toBe('');
    expect(toSearchParams({ ...NEWEST_SESSION_QUERY, page_size: 50 }).toString()).toBe('page_size=50');
  });

  it('round-trips applied state through the browser URL', () => {
    const query = {
      filters: filters({ status: 'FAILED', boundary: ' a b ', started_from: '2026-10-01T03:37:00.000Z' }),
      page_size: 100,
      cursor: 'djF8bmV4dHwx',
    } as const;
    expect(parseSessionQuery(toSearchParams(query))).toEqual({ ok: true, query });
  });

  it('always states the effective page size on an API request', () => {
    const params = new URLSearchParams();
    appendQueryParams(params, NEWEST_SESSION_QUERY);
    expect(params.toString()).toBe('page_size=25');
  });
});

describe('form drafts', () => {
  it('seeds date inputs with local values and other inputs verbatim', () => {
    expect(draftFromFilters(filters({
      status: 'COMPLETED',
      boundary: ' Check ',
      started_from: '2026-10-01T03:37:04.123Z',
    }))).toEqual(draft({
      status: 'COMPLETED',
      boundary: ' Check ',
      started_from: '2026-10-01T09:07:04.123',
    }));
  });

  it('omits blank and whitespace-only text but keeps other values exactly', () => {
    expect(filtersFromDraft(draft({ boundary: '   ', invoked_by_email: '\t' }), EMPTY_SESSION_FILTERS))
      .toEqual({ ok: true, filters: EMPTY_SESSION_FILTERS });
    expect(filtersFromDraft(draft({ boundary: ' Check.out* ', invoked_by_email: 'Operator@Example.invalid' }), EMPTY_SESSION_FILTERS))
      .toEqual({ ok: true, filters: filters({ boundary: ' Check.out* ', invoked_by_email: 'Operator@Example.invalid' }) });
  });

  it('keeps an unedited date input at its exact applied instant', () => {
    const applied = filters({ started_from: '2026-10-01T03:37:04.123Z' });
    expect(filtersFromDraft(draftFromFilters(applied), applied)).toEqual({ ok: true, filters: applied });
  });

  it('converts an edited date input from local time', () => {
    const applied = filters({ started_from: '2026-10-01T03:37:04.123Z' });
    expect(filtersFromDraft(draft({ started_from: '2026-10-02T09:07' }), applied))
      .toEqual({ ok: true, filters: filters({ started_from: '2026-10-02T03:37:00.000Z' }) });
  });

  it.each([
    [draft({ started_from: '2026-10-01' }), 'Started from needs a complete date and time.'],
    [draft({ status: 'DONE' }), 'Status is not a known value.'],
    [draft({ boundary: 'x'.repeat(257) }), 'Boundary must be 256 characters or fewer.'],
    [
      draft({ started_from: '2026-10-02T09:07', started_before: '2026-10-01T09:07' }),
      'Started from must be earlier than started before.',
    ],
  ])('reports the problem with a submitted draft: %j', (values, message) => {
    expect(filtersFromDraft(values, EMPTY_SESSION_FILTERS)).toEqual({ ok: false, message });
  });

  it('counts only applied filters', () => {
    expect(activeFilterCount(EMPTY_SESSION_FILTERS)).toBe(0);
    expect(activeFilterCount(filters({ status: 'FAILED', boundary: 'checkout' }))).toBe(2);
  });
});
