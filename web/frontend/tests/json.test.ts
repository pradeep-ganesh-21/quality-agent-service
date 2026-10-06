import { describe, expect, it } from 'vitest';

import { parseJson, stringifyJson } from '../src/json';
import type { JsonValue } from '../src/types';

describe('exact JSON numbers', () => {
  it.each([
    ['0', 0],
    ['-42', -42],
    ['9007199254740991', Number.MAX_SAFE_INTEGER],
    ['-9007199254740991', Number.MIN_SAFE_INTEGER],
    ['9007199254740992', 9007199254740992n],
    ['9007199254740993', 9007199254740993n],
    ['-9007199254740993', -9007199254740993n],
    ['9223372036854775807', 9223372036854775807n],
    ['-9223372036854775808', -9223372036854775808n],
    ['1.25', 1.25],
    ['1e100', 1e100],
    ['5e-324', 5e-324],
    ['"9223372036854775807"', '9223372036854775807'],
  ])('parses %s without rounding integer tokens', (text, expected) => {
    expect(parseJson(text)).toBe(expected);
  });

  it('serializes bigints as unquoted JSON numbers at every depth', () => {
    const text = '{"large":9223372036854775807,"nested":[-9223372036854775808,{"n":9007199254740993}],"text":"9223372036854775807"}';
    expect(stringifyJson(parseJson(text))).toBe(text);
  });

  it('preserves fractional and exponential JSON-number semantics', () => {
    const value = parseJson('[1.25,1e100,-2.5e-10,0.0]');
    expect(parseJson(stringifyJson(value))).toEqual(value);
  });

  it.each(['NaN', 'Infinity', '-Infinity', '1e999', '{', '', '[1,]', '{"n":.5}'])(
    'rejects malformed or non-finite JSON: %s',
    (text) => expect(() => parseJson(text)).toThrow(SyntaxError),
  );

  it.each([NaN, Infinity, -Infinity])('does not serialize %s as null', (number) => {
    expect(() => stringifyJson({ number })).toThrow(TypeError);
  });
});

describe('opaque JSON values', () => {
  it('preserves special keys as own properties, without changing prototypes', () => {
    const text = '{"__proto__":{"polluted":true},"constructor":{"prototype":{"x":1}},"_id":"nested","a.b":{"$set":"$status"},"array":[null,true,"<script>x</script>"]}';
    const value = parseJson(text);
    expect(Object.hasOwn(value as object, '__proto__')).toBe(true);
    expect(Object.getPrototypeOf(value)).toBe(Object.prototype);
    expect(Object.prototype).not.toHaveProperty('polluted');
    expect(stringifyJson(value)).toBe(text);
  });

  it('does not interpret number-like or raw-JSON-like objects as numeric values', () => {
    const text = '{"isLosslessNumber":true,"value":"9007199254740993","rawJSON":"9223372036854775807","toJSON":"plain data"}';
    expect(stringifyJson(parseJson(text))).toBe(text);
  });

  it('uses last-value-wins for duplicate keys, including __proto__', () => {
    const value = parseJson('{"n":1,"n":9223372036854775807,"__proto__":0,"__proto__":1}');
    expect(stringifyJson(value)).toBe('{"n":9223372036854775807,"__proto__":1}');
  });

  it('preserves strings, escapes, nulls, booleans, and empty containers', () => {
    const value: JsonValue = {
      text: 'Quote: " slash: \\ newline: \n NUL: \0 Unicode: 日本語',
      nil: null,
      boolean: false,
      object: {},
      array: [],
    };
    expect(parseJson(stringifyJson(value))).toEqual(value);
  });

  it('handles document depth plus detail-response nesting without a new cap', () => {
    const text = '['.repeat(103) + '9223372036854775807' + ']'.repeat(103);
    expect(stringifyJson(parseJson(text))).toBe(text);
  });

  it('does not mutate values during serialization', () => {
    const nested = [1n, null, 'text'];
    const value = { nested };
    Object.freeze(nested);
    Object.freeze(value);
    expect(stringifyJson(value)).toBe('{"nested":[1,null,"text"]}');
  });
});
