import { useCallback, useMemo } from 'react';
import type { MouseEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { listSessionFields } from './api';
import { ErrorNotice, LoadingNotice } from './ReadNotice';
import { requiredSessionFields, SESSION_COLUMNS } from './sessionColumns';
import type { SessionColumn } from './sessionColumns';
import { useApiRead } from './useApiRead';

export function SessionList({ columns = SESSION_COLUMNS }: { columns?: readonly SessionColumn[] }) {
  return (
    <section aria-labelledby="sessions-heading">
      <header className="page-heading">
        <p className="eyebrow">Execution records</p>
        <h1 id="sessions-heading">Sessions</h1>
        <p className="muted">Open a session to inspect its execution record.</p>
      </header>
      {columns.length === 0
        ? <p className="notice" role="alert">No session columns are configured.</p>
        : <SessionRows columns={columns} />}
    </section>
  );
}

function SessionRows({ columns }: { columns: readonly SessionColumn[] }) {
  const fields = useMemo(() => requiredSessionFields(columns), [columns]);
  const load = useCallback((signal: AbortSignal) => listSessionFields(fields, signal), [fields]);
  const state = useApiRead(`sessions:${JSON.stringify(fields)}`, load);
  const navigate = useNavigate();

  function openRow(event: MouseEvent<HTMLTableRowElement>, path: string) {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    if (event.target instanceof Element && event.target.closest('a, button, input, select, textarea, summary')) return;
    if (window.getSelection()?.isCollapsed === false) return;
    void navigate(path);
  }

  return (
    <>
      {state.status === 'loading' && <LoadingNotice>Loading sessions…</LoadingNotice>}
      {state.status === 'error' && <ErrorNotice error={state.error} />}
      {state.status === 'ready' && (state.data.length === 0
        ? <p className="notice" role="status">No sessions have been recorded yet.</p>
        : <div className="table-scroll" tabIndex={0} role="region" aria-label="Session history">
            <table className="session-table">
              <caption className="sr-only">Recorded sessions, newest first</caption>
              <thead><tr>{columns.map((column) => <th key={column.key} scope="col">{column.header}</th>)}</tr></thead>
              <tbody>{state.data.map((session) => {
                const path = `/sessions/${encodeURIComponent(session.session_id)}`;
                return (
                  <tr key={session.session_id} onClick={(event) => openRow(event, path)}>
                    {columns.map((column, index) => (
                      <td key={column.key}>{index === 0
                        ? <Link to={path}>
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
    </>
  );
}
