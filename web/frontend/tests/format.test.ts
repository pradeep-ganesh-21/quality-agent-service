import { describe, expect, it } from 'vitest';

import { formatCount, formatJson, formatTimestamp } from '../src/format';
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
  it.each([
    ['2026-10-01T09:07:04.123Z', '2026-10-01 09:07:04.123 UTC'],
    ['2026-10-01T09:07:04Z', '2026-10-01 09:07:04.000 UTC'],
    ['2026-10-01T00:30:00.001+02:00', '2026-09-30 22:30:00.001 UTC'],
    ['2026-10-01T23:30:00.999-02:00', '2026-10-02 01:30:00.999 UTC'],
    ['0001-01-01T00:00:00.000Z', '0001-01-01 00:00:00.000 UTC'],
    [null, 'unknown'],
  ])('formats %s independently of the local timezone', (value, expected) => {
    expect(formatTimestamp(value)).toBe(expected);
  });

  it('does not silently display an invalid date', () => {
    expect(() => formatTimestamp('not a timestamp')).toThrow(RangeError);
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
