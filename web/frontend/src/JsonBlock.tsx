import { useId, useState } from 'react';

import { formatJson } from './format';
import type { JsonValue } from './types';

export function JsonValueText({ value }: { value: JsonValue | undefined }) {
  if (value === undefined) return <span className="muted">Not provided</span>;
  return typeof value === 'string' ? value : <code className="json-cell">{formatJson(value)}</code>;
}

export function JsonBlock({ label, value }: { label: string; value: JsonValue }) {
  const [open, setOpen] = useState(false);
  const labelId = useId();
  return (
    <details className="json-block" onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary id={labelId}>{label}</summary>
      {open && <pre role="group" tabIndex={0} aria-labelledby={labelId}>{formatJson(value)}</pre>}
    </details>
  );
}
