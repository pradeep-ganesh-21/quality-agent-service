// @vitest-environment node
import { execFileSync } from 'node:child_process';
import { expect, it } from 'vitest';

it('preserves JSON values without native source-token or raw-JSON support', () => {
  // core-js detects capabilities once on import. A fresh process avoids its CJS
  // cache and exercises the fallback without changing other tests' globals.
  const moduleUrl = new URL('../src/json.ts', import.meta.url).href;
  const output = execFileSync(process.execPath, [
    '--experimental-strip-types', '--input-type=module', '-e', `
      import assert from 'node:assert/strict';
      const nativeParse = JSON.parse;
      JSON.parse = (text, reviver) => nativeParse(text, reviver
        ? (key, value) => reviver(key, value)
        : undefined);
      Reflect.deleteProperty(JSON, 'rawJSON');
      Reflect.deleteProperty(JSON, 'isRawJSON');
      const parseWithoutSource = JSON.parse;
      const { parseJson, stringifyJson } = await import(${JSON.stringify(moduleUrl)});
      const text = '{"__proto__":{"n":9223372036854775807},"a.b":[{"$set":-9223372036854775808},{"rawJSON":"9007199254740993","isLosslessNumber":true}],"string":"9223372036854775807"}';
      const value = parseJson(text);
      assert.equal(stringifyJson(value), text);
      assert.equal(value['__proto__'].n, 9223372036854775807n);
      assert.equal(Object.hasOwn(value, '__proto__'), true);
      assert.equal(Object.getPrototypeOf(value), Object.prototype);
      assert.equal(stringifyJson(parseJson('{"n":1,"n":9223372036854775807}')), '{"n":9223372036854775807}');
      const deep = '['.repeat(103) + '9223372036854775807' + ']'.repeat(103);
      assert.equal(stringifyJson(parseJson(deep)), deep);
      assert.throws(() => parseJson('1e999'), SyntaxError);
      assert.equal(JSON.parse, parseWithoutSource);
      assert.equal(Object.hasOwn(JSON, 'rawJSON'), false);
      assert.equal(Object.hasOwn(JSON, 'isRawJSON'), false);
      console.log('Fallback JSON checks passed.');
    `,
  ], { encoding: 'utf8', timeout: 10_000 });
  expect(output.trim()).toBe('Fallback JSON checks passed.');
});
