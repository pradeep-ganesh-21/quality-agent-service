import { useId, useState } from 'react';
import type { FormEvent } from 'react';

import { SESSION_FILTER_LABELS } from './sessionQuery';
import { EMPTY_SESSION_FILTERS, SESSION_STATUSES } from './types';
import type { SessionFilterDraft, SessionFilterName, SessionStatus } from './types';

// Human labels for the control only. The submitted value stays the API token.
const STATUS_LABELS: Readonly<Record<SessionStatus, string>> = {
  IN_PROGRESS: 'In progress',
  COMPLETED: 'Completed',
  FAILED: 'Failed',
};

export function SessionFilters({
  initial,
  zone,
  error,
  onApply,
  onClear,
}: {
  initial: SessionFilterDraft;
  zone: string;
  error: string;
  onApply: (draft: SessionFilterDraft) => void;
  onClear: () => void;
}) {
  // Editing is a draft: nothing is requested until the form is submitted.
  const [draft, setDraft] = useState(initial);
  const prefix = useId();
  const fieldId = (name: SessionFilterName) => `${prefix}-${name}`;

  function update(name: SessionFilterName, value: string) {
    setDraft((current) => ({ ...current, [name]: value }));
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onApply(draft);
  }

  return (
    <form className="filter-panel" onSubmit={submit} aria-label="Session filters">
      <div className="filter-grid">
        <div className="filter-field">
          <label htmlFor={fieldId('status')}>{SESSION_FILTER_LABELS.status}</label>
          <select
            id={fieldId('status')}
            value={draft.status}
            onChange={(event) => update('status', event.target.value)}
          >
            <option value="">All statuses</option>
            {SESSION_STATUSES.map((status) => (
              <option key={status} value={status}>{STATUS_LABELS[status]}</option>
            ))}
          </select>
        </div>

        <div className="filter-field">
          <label htmlFor={fieldId('boundary')}>{SESSION_FILTER_LABELS.boundary}</label>
          <input
            id={fieldId('boundary')}
            type="text"
            value={draft.boundary}
            onChange={(event) => update('boundary', event.target.value)}
            aria-describedby={`${prefix}-boundary-hint`}
          />
          <p className="filter-hint" id={`${prefix}-boundary-hint`}>Matches any part of the boundary, ignoring case.</p>
        </div>

        <div className="filter-field">
          <label htmlFor={fieldId('invoked_by_email')}>{SESSION_FILTER_LABELS.invoked_by_email}</label>
          <input
            id={fieldId('invoked_by_email')}
            type="text"
            value={draft.invoked_by_email}
            onChange={(event) => update('invoked_by_email', event.target.value)}
            aria-describedby={`${prefix}-email-hint`}
          />
          <p className="filter-hint" id={`${prefix}-email-hint`}>Must match the whole address exactly.</p>
        </div>

        <div className="filter-field">
          <label htmlFor={fieldId('started_from')}>{SESSION_FILTER_LABELS.started_from}</label>
          <input
            id={fieldId('started_from')}
            type="datetime-local"
            step="1"
            value={draft.started_from}
            onChange={(event) => update('started_from', event.target.value)}
          />
        </div>

        <div className="filter-field">
          <label htmlFor={fieldId('started_before')}>{SESSION_FILTER_LABELS.started_before}</label>
          <input
            id={fieldId('started_before')}
            type="datetime-local"
            step="1"
            value={draft.started_before}
            onChange={(event) => update('started_before', event.target.value)}
            aria-describedby={`${prefix}-range-hint`}
          />
          <p className="filter-hint" id={`${prefix}-range-hint`}>Times are in {zone}. This bound is excluded.</p>
        </div>
      </div>

      {error !== '' && <p className="notice notice-error filter-error" role="alert">{error}</p>}

      <div className="filter-actions">
        <button type="submit" className="button-primary">Apply filters</button>
        <button
          type="button"
          onClick={() => {
            setDraft(EMPTY_SESSION_FILTERS);
            onClear();
          }}
        >
          Clear filters
        </button>
      </div>
    </form>
  );
}
