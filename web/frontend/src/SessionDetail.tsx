import { useCallback } from 'react';
import { Link, useLocation, useParams } from 'react-router-dom';

import { getSession } from './api';
import { formatCount, formatTimestamp, localZoneLabel } from './format';
import { JsonBlock, JsonValueText } from './JsonBlock';
import { ErrorNotice, LoadingNotice } from './ReadNotice';
import type { SessionDetail as SessionDetailRecord } from './types';
import { useApiRead } from './useApiRead';

// The list passes its own path so filters and the current page survive a return.
function listPathFromState(state: unknown): string {
  if (typeof state !== 'object' || state === null) return '/';
  const path: unknown = (state as { listPath?: unknown }).listPath;
  // Honour only an in-application path, never a protocol-relative or absolute URL.
  if (typeof path !== 'string' || !path.startsWith('/') || path.startsWith('//')) return '/';
  return path;
}

export function SessionDetail() {
  const { sessionId = '' } = useParams();
  const { state } = useLocation();
  const load = useCallback((signal: AbortSignal) => getSession(sessionId, signal), [sessionId]);
  const read = useApiRead(`session:${sessionId}`, load);

  return (
    <section aria-labelledby="session-heading">
      <header className="page-heading">
        <Link className="back-link" to={listPathFromState(state)}>← All sessions</Link>
        <h1 id="session-heading">Session details</h1>
        <p className="muted">Times are shown in {localZoneLabel()}.</p>
      </header>
      {read.status === 'loading' && <LoadingNotice>Loading session…</LoadingNotice>}
      {read.status === 'error' && <ErrorNotice error={read.error} />}
      {read.status === 'ready' && <SessionRecord key={read.data.session_id} session={read.data} />}
    </section>
  );
}

function SessionRecord({ session }: { session: SessionDetailRecord }) {
  return (
    <div className="record">
      <section className="record-section" aria-labelledby="summary-heading">
        <div className="section-heading">
          <h2 id="summary-heading">Session</h2>
          <span className="status-label">{session.status}</span>
        </div>
        <dl className="record-fields">
          <div className="wide-field"><dt>Session ID</dt><dd><code>{session.session_id}</code></dd></div>
          <div><dt>Schema version</dt><dd>{session.schema_version}</dd></div>
          <div><dt>Started at</dt><dd><time dateTime={session.started_at}>{formatTimestamp(session.started_at)}</time></dd></div>
          <div><dt>Received at</dt><dd><time dateTime={session.received_at}>{formatTimestamp(session.received_at)}</time></dd></div>
          <div><dt>Completed at</dt><dd>{formatTimestamp(session.completion_time)}</dd></div>
          <div className="wide-field"><dt>Last steps executed</dt><dd>{session.last_step_executed.length === 0
            ? <span className="muted">No steps recorded</span>
            : <ul className="step-names">{session.last_step_executed.map((step, index) => <li key={index}>{step}</li>)}</ul>}
          </dd></div>
        </dl>
      </section>

      <section className="record-section" aria-labelledby="outcome-heading">
        <h2 id="outcome-heading">Execution outcome</h2>
        <dl className="outcome-fields">
          <div><dt>Defects</dt><dd>{formatCount(session.execution_outcome?.defect_count)}</dd></div>
          <div><dt>Gaps</dt><dd>{formatCount(session.execution_outcome?.gap_count)}</dd></div>
          <div><dt>Contract ingredients</dt><dd>{formatCount(session.execution_outcome?.contract_ingredient_count)}</dd></div>
        </dl>
        <JsonBlock label="Execution outcome JSON" value={session.execution_outcome} />
      </section>

      <section className="record-section" aria-labelledby="metadata-heading">
        <h2 id="metadata-heading">Metadata</h2>
        <dl className="identity-fields">
          {(['recorded_by', 'invoked_by'] as const).map((field) => (
            <div key={field}><dt>{field === 'recorded_by' ? 'Recorded by' : 'Invoked by'}</dt>
              <dd><JsonValueText value={Object.hasOwn(session.metadata, field) ? session.metadata[field] : undefined} /></dd>
            </div>
          ))}
        </dl>
        <JsonBlock label="Metadata JSON" value={session.metadata} />
      </section>

      <section className="record-section" aria-labelledby="runs-heading">
        <h2 id="runs-heading">Runs</h2>
        {session.runs.length === 0
          ? <p className="muted">No runs have been recorded for this session.</p>
          : <div className="run-list">{session.runs.map((run) => (
              <article className="run-record" key={run.run_id} aria-label={`Run ${run.run_id}`}>
                <div className="section-heading"><h3>{run.step}</h3><span className="verdict">{run.verdict}</span></div>
                <dl className="record-fields">
                  <div><dt>Run ID</dt><dd><code>{run.run_id}</code></dd></div>
                  <div><dt>Session ID</dt><dd><code>{run.session_id}</code></dd></div>
                  <div><dt>Schema version</dt><dd>{run.schema_version}</dd></div>
                  <div><dt>Command</dt><dd><code>{run.command}</code></dd></div>
                  <div><dt>Occurred at</dt><dd><time dateTime={run.occurred_at}>{formatTimestamp(run.occurred_at)}</time></dd></div>
                  <div><dt>Received at</dt><dd><time dateTime={run.received_at}>{formatTimestamp(run.received_at)}</time></dd></div>
                </dl>
                <JsonBlock label={`Run details JSON — ${run.run_id}`} value={run.details} />
              </article>
            ))}</div>}
      </section>

      <JsonBlock label="Full session JSON" value={session} />
    </div>
  );
}
