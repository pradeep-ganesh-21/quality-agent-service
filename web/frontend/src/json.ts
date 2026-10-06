import parse from 'core-js-pure/actual/json/parse.js';
import rawJSON from 'core-js-pure/actual/json/raw-json.js';
import stringify from 'core-js-pure/actual/json/stringify.js';

import type { JsonValue } from './types';

export function parseJson(text: string): JsonValue {
  const value = parse(text, (_key, value, context) => {
    if (typeof value !== 'number') return value;

    const source = context.source;
    if (source === undefined) {
      throw new SyntaxError('The JSON parser did not provide a number source token.');
    }

    // The native numeric value may already be rounded; recover from the token.
    if (/^-?\d+$/.test(source) && !Number.isSafeInteger(value)) {
      return BigInt(source);
    }
    if (!Number.isFinite(value)) {
      throw new SyntaxError('JSON numbers must be finite.');
    }
    return value;
  });

  // Parsing produces only JSON values, with bigint as the sole extension above.
  return value as JsonValue;
}

export function stringifyJson(value: JsonValue, space?: number): string {
  const text = stringify(value, (_key, child) => {
    if (typeof child === 'bigint') return rawJSON(child.toString());
    if (typeof child === 'number' && !Number.isFinite(child)) {
      throw new TypeError('JSON numbers must be finite.');
    }
    return child;
  }, space);

  if (text === undefined) throw new TypeError('Expected a JSON value.');
  return text;
}
