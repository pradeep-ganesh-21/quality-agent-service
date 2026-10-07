import { describe, expect, it } from 'vitest';

import { parseJson } from '../src/json';
import { readSessionField, requiredSessionFields, SESSION_COLUMNS } from '../src/sessionColumns';
import type { SessionListRecord } from '../src/types';
import { SESSION_ID } from './fixtures';

describe('column configuration', () => {
  it('declares exactly the three requested columns and their field dependencies', () => {
    expect(SESSION_COLUMNS.map((column) => column.header)).toEqual(['Started at (UTC)', 'Invoked by', 'Boundary']);
    expect(requiredSessionFields(SESSION_COLUMNS)).toEqual(['started_at', 'metadata.invoked_by.name', 'metadata.boundary']);
  });

  it('deduplicates dependencies without changing column order', () => {
    const columns = [...SESSION_COLUMNS, {
      key: 'duplicate', header: 'Duplicate', requiredFields: ['started_at'] as const, renderCell: () => 'value',
    }];
    expect(requiredSessionFields(columns)).toEqual(requiredSessionFields(SESSION_COLUMNS));
    expect(columns.map((column) => column.key)).toEqual(['started_at', 'invoked_by', 'boundary', 'duplicate']);
  });

  it.each([
    {}, { invoked_by: null }, { invoked_by: 'not an object' },
    { invoked_by: ['not an object'] }, { invoked_by: {} },
  ])('tolerates missing or non-object intermediate values: %j', (metadata) => {
    expect(readSessionField({ session_id: SESSION_ID, metadata }, 'metadata.invoked_by.name')).toBeUndefined();
  });

  it('reads own special keys without following inherited properties', () => {
    const metadata = parseJson('{"__proto__":{"name":"own data"}}');
    const row: SessionListRecord = { session_id: SESSION_ID, metadata: { nested: metadata } };
    expect(readSessionField(row, 'metadata.nested.__proto__.name')).toBe('own data');
    expect(readSessionField(row, 'metadata.constructor')).toBeUndefined();
    expect(readSessionField(row, 'metadata.toString')).toBeUndefined();
  });
});
