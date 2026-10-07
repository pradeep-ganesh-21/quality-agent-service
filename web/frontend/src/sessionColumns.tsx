import type { ReactNode } from 'react';

import { formatTimestamp } from './format';
import { JsonValueText } from './JsonBlock';
import type { JsonValue, SessionFieldPath, SessionListRecord } from './types';

export type SessionColumn = Readonly<{
  key: string;
  header: string;
  requiredFields: readonly SessionFieldPath[];
  renderCell: (session: SessionListRecord) => ReactNode;
}>;

export function readSessionField(session: SessionListRecord, path: SessionFieldPath): JsonValue | undefined {
  let value: JsonValue = session;
  for (const part of path.split('.')) {
    if (value === null || typeof value !== 'object' || Array.isArray(value) || !Object.hasOwn(value, part)) {
      return undefined;
    }
    const child: JsonValue | undefined = value[part];
    if (child === undefined) return undefined;
    value = child;
  }
  return value;
}

// Column order, field dependencies, and presentation are configured together.
export const SESSION_COLUMNS: readonly SessionColumn[] = [
  {
    key: 'started_at',
    header: 'Started at (UTC)',
    requiredFields: ['started_at'],
    renderCell: (session) => session.started_at === undefined
      ? <JsonValueText value={undefined} />
      : <time dateTime={session.started_at}>{formatTimestamp(session.started_at)}</time>,
  },
  {
    key: 'invoked_by',
    header: 'Invoked by',
    requiredFields: ['metadata.invoked_by.name'],
    renderCell: (session) => <JsonValueText value={readSessionField(session, 'metadata.invoked_by.name')} />,
  },
  {
    key: 'boundary',
    header: 'Boundary',
    requiredFields: ['metadata.boundary'],
    renderCell: (session) => <JsonValueText value={readSessionField(session, 'metadata.boundary')} />,
  },
];

export function requiredSessionFields(columns: readonly SessionColumn[]): SessionFieldPath[] {
  return [...new Set(columns.flatMap((column) => column.requiredFields))];
}
