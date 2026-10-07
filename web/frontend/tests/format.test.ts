import { describe, expect, it } from 'vitest';

import { formatCount, formatJson, formatTimestamp, localZoneLabel } from '../src/format';
import { parseJson } from '../src/json';

describe('formatCount', () => {
  it.each([
    [undefined, 'unknown'],
    [null, 'unknown'],
    [0, '0'],
    [0n, '0'],
    [42, '42'],
    [9223372036854775807n, '9223372036854775807'],
  ])('formats %s as %s', (value, expected) => {
    expect(formatCount(value)).toBe(expected);
  });
});

describe('formatTimestamp', () => {
  it('runs in the pinned test time zone', () => {
    // Local rendering is only meaningful against a known, non-UTC zone.
    expect(new Date('2026-10-01T00:00:00.000Z').getTimezoneOffset()).toBe(-330);
  });

  it.each([
    ['2026-10-01T09:07:04.123Z', '2026-10-01 14:37:04.123'],
    ['2026-10-01T09:07:04Z', '2026-10-01 14:37:04.000'],
    ['2026-10-01T00:30:00.001+02:00', '2026-10-01 04:00:00.001'],
    ['2026-10-01T23:30:00.999-02:00', '2026-10-02 07:00:00.999'],
    // Before standard time existed this zone used local mean time (+05:53:28).
    ['0001-01-01T00:00:00.000Z', '0001-01-01 05:53:28.000'],
    [null, 'unknown'],
  ])('formats %s in the browser time zone', (value, expected) => {
    expect(formatTimestamp(value)).toBe(expected);
  });

  it('does not silently display an invalid date', () => {
    expect(() => formatTimestamp('not a timestamp')).toThrow(RangeError);
  });
});

describe('localZoneLabel', () => {
  it('names the zone the browser resolved', () => {
    expect(localZoneLabel()).toBe(Intl.DateTimeFormat().resolvedOptions().timeZone);
  });

  it('falls back to the current offset when no zone name is available', () => {
    const resolved = Intl.DateTimeFormat.prototype.resolvedOptions;
    try {
      Intl.DateTimeFormat.prototype.resolvedOptions = function patched(this: Intl.DateTimeFormat) {
        return { ...resolved.call(this), timeZone: '' };
      };
      expect(localZoneLabel()).toBe('UTC+05:30');
    } finally {
      Intl.DateTimeFormat.prototype.resolvedOptions = resolved;
    }
  });
});

describe('formatJson', () => {
  it('indents exact numbers without turning them into quoted strings', () => {
    const value = parseJson('{"count":9223372036854775807,"nested":{"text":"9223372036854775807"}}');
    expect(formatJson(value)).toBe(`{
  "count": 9223372036854775807,
  "nested": {
    "text": "9223372036854775807"
  }
}`);
  });

  it('returns stored markup as text and does not create DOM nodes', () => {
    const value = { text: '<img src=x onerror="alert(1)">' };
    expect(formatJson(value)).toBe(JSON.stringify(value, null, 2));
    expect(document.querySelector('img')).toBeNull();
  });
});
