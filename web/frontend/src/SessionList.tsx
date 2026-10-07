import { useCallback, useId, useMemo, useState } from 'react';
import type { MouseEvent } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';

import { listSessionFields } from './api';
import { formatCount, localZoneLabel } from './format';
import { ErrorNotice, LoadingNotice } from './ReadNotice';
import { SessionFilters } from './SessionFilters';
import { requiredSessionFields, SESSION_COLUMNS } from './sessionColumns';
import type { SessionColumn } from './sessionColumns';
import {
  activeFilterCount,
  draftFromFilters,
  filtersFromDraft,
  parseSessionQuery,
  toSearchParams,
} from './sessionQuery';
import { DEFAULT_SESSION_PAGE_SIZE, EMPTY_SESSION_FILTERS, SESSION_PAGE_SIZES } from './types';
import type {
  JsonNumber,
  SessionFilterDraft,
  SessionListRecord,
  SessionPage,
  SessionPageSize,
  SessionQuery,
} from './types';
import { useApiRead } from './useApiRead';

export function SessionList({ columns = SESSION_COLUMNS }: { columns?: readonly SessionColumn[] }) {
  const [searchParams, setSearchParams] = useSearchParams();
  // Applied state lives in the URL, so refresh, sharing, and history all work.
  const parsed = useMemo(() => parseSessionQuery(searchParams), [searchParams]);
  const query = parsed.ok ? parsed.query : null;
  const filters = query?.filters ?? EMPTY_SESSION_FILTERS;
  const activeCount = activeFilterCount(filters);
  const [panelOpen, setPanelOpen] = useState(activeCount > 0 || !parsed.ok);
  const [formError, setFormError] = useState('');
  const panelId = useId();
  const zone = localZoneLabel();

  function navigateTo(next: SessionQuery) {
    setFormError('');
    const params = toSearchParams(next);
    // Re-applying an identical query would only add a dead history entry.
    if (params.toString() === searchParams.toString()) return;
    setSearchParams(params);
  }

  function applyDraft(draft: SessionFilterDraft) {
    const result = filtersFromDraft(draft, filters);
    if (!result.ok) {
      setFormError(result.message);
      return;
    }
    // A different filter set invalidates the cursor: start at the newest page.
    navigateTo({
      filters: result.filters,
      page_size: query?.page_size ?? DEFAULT_SESSION_PAGE_SIZE,
      cursor: '',
    });
  }

  return (
    <section aria-labelledby="sessions-heading">
      <header className="page-heading">
        <p className="eyebrow">Execution records</p>
        <h1 id="sessions-heading">Sessions</h1>
        <p className="muted">Open a session to inspect its execution record. Times are shown in {zone}.</p>
      </header>

      <div className="filter-bar">
        <button
          type="button"
          className="filter-toggle"
          aria-expanded={panelOpen}
          aria-controls={panelId}
          onClick={() => setPanelOpen(!panelOpen)}
        >
          Filters{activeCount > 0 && ` (${activeCount})`}
        </button>
      </div>
      {/* Hiding keeps the form mounted, so unsubmitted edits are not discarded. */}
      <div id={panelId} hidden={!panelOpen}>
        <SessionFilters
          key={JSON.stringify(filters)}
          initial={draftFromFilters(filters)}
          zone={zone}
          error={formError}
          onApply={applyDraft}
          onClear={() => { navigateTo({ filters: EMPTY_SESSION_FILTERS, page_size: query?.page_size ?? DEFAULT_SESSION_PAGE_SIZE, cursor: '' }); }}
        />
      </div>

      {!parsed.ok && <p className="notice notice-error" role="alert">{parsed.message}</p>}
      {parsed.ok && (columns.length === 0
        ? <p className="notice" role="alert">No session columns are configured.</p>
        : <SessionRows
            columns={columns}
            query={parsed.query}
            filtered={activeCount > 0}
            onNavigate={navigateTo}
          />)}
    </section>
  );
}

function SessionRows({ columns, query, filtered, onNavigate }: {
  columns: readonly SessionColumn[];
  query: SessionQuery;
  filtered: boolean;
  onNavigate: (next: SessionQuery) => void;
}) {
  const fields = useMemo(() => requiredSessionFields(columns), [columns]);
  const load = useCallback(
    (signal: AbortSignal) => listSessionFields(fields, query, signal),
    [fields, query],
  );
  // Every request input belongs in the key: fields, filters, page size, cursor.
  const state = useApiRead(JSON.stringify([fields, query]), load);
  const navigate = useNavigate();
  const listPath = useMemo(() => {
    const search = toSearchParams(query).toString();
    return search === '' ? '/' : `/?${search}`;
  }, [query]);

  function openRow(event: MouseEvent<HTMLTableRowElement>, path: string) {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    if (event.target instanceof Element && event.target.closest('a, button, input, select, textarea, summary')) return;
    if (window.getSelection()?.isCollapsed === false) return;
    void navigate(path, { state: { listPath } });
  }

  const page = state.status === 'ready' ? state.data : null;

  return (
    <>
      {state.status === 'loading' && <LoadingNotice>Loading sessions…</LoadingNotice>}
      {state.status === 'error' && <ErrorNotice error={state.error} />}
      {page !== null && (page.items.length === 0
        ? <EmptyPage page={page} filtered={filtered} onNewest={() => onNavigate({ ...query, cursor: '' })} />
        : <div className="table-scroll" tabIndex={0} role="region" aria-label="Session history">
            <table className="session-table">
              <caption className="sr-only">Recorded sessions, newest first</caption>
              <thead><tr>{columns.map((column) => <th key={column.key} scope="col">{column.header}</th>)}</tr></thead>
              <tbody>{page.items.map((session) => {
                const path = `/sessions/${encodeURIComponent(session.session_id)}`;
                return (
                  <tr key={session.session_id} onClick={(event) => openRow(event, path)}>
                    {columns.map((column, index) => (
                      <td key={column.key}>{index === 0
                        ? <Link to={path} state={{ listPath }}>
                            {column.renderCell(session)}
                            <span className="sr-only"> — open session {session.session_id}</span>
                          </Link>
                        : column.renderCell(session)}
                      </td>
                    ))}
                  </tr>
                );
              })}</tbody>
            </table>
          </div>
      )}
      <PageControls page={page} query={query} filtered={filtered} onNavigate={onNavigate} />
    </>
  );
}

function EmptyPage({ page, filtered, onNewest }: {
  page: SessionPage<SessionListRecord>;
  filtered: boolean;
  onNewest: () => void;
}) {
  if (isZero(page.total_count)) {
    return (
      <p className="notice" role="status">
        {filtered ? 'No sessions match these filters.' : 'No sessions have been recorded yet.'}
      </p>
    );
  }
  // A cursor can outlive the records it pointed at; the count is still live.
  return (
    <div className="notice" role="status">
      <p>This page has no sessions. The matching sessions changed after this link was created.</p>
      <button type="button" onClick={onNewest}>Return to newest sessions</button>
    </div>
  );
}

function PageControls({ page, query, filtered, onNavigate }: {
  page: SessionPage<SessionListRecord> | null;
  query: SessionQuery;
  filtered: boolean;
  onNavigate: (next: SessionQuery) => void;
}) {
  const pageSizeId = useId();
  const previous = page?.previous_cursor ?? null;
  const next = page?.next_cursor ?? null;

  return (
    <div className="table-footer">
      {page !== null && (
        <p className="muted result-count">
          {`${sessionCount(page.items.length)} on this page · ${sessionCount(page.total_count)} ${filtered ? 'matching these filters' : 'recorded'}`}
        </p>
      )}
      <div className="page-controls">
        <label htmlFor={pageSizeId}>Rows per page</label>
        <select
          id={pageSizeId}
          value={query.page_size}
          onChange={(event) => {
            // A different page size invalidates the cursor as well.
            onNavigate({ ...query, page_size: Number(event.target.value) as SessionPageSize, cursor: '' });
          }}
        >
          {SESSION_PAGE_SIZES.map((size) => <option key={size} value={size}>{size}</option>)}
        </select>
        <button
          type="button"
          disabled={previous === null}
          onClick={() => { if (previous !== null) onNavigate({ ...query, cursor: previous }); }}
        >
          Previous
        </button>
        <button
          type="button"
          disabled={next === null}
          onClick={() => { if (next !== null) onNavigate({ ...query, cursor: next }); }}
        >
          Next
        </button>
      </div>
    </div>
  );
}

function isZero(value: JsonNumber): boolean {
  return value === 0 || value === 0n;
}

function sessionCount(value: JsonNumber): string {
  return `${formatCount(value)} ${value === 1 || value === 1n ? 'session' : 'sessions'}`;
}
