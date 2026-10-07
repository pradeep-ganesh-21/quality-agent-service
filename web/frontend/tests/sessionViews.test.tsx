import { StrictMode } from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Link, MemoryRouter, useNavigate } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { App } from '../src/App';
import { SESSION_COLUMNS } from '../src/sessionColumns';
import type { SessionColumn } from '../src/sessionColumns';
import { LARGE_DETAIL_JSON, page, run, SESSION_ID, summary } from './fixtures';

const OTHER_ID = '68df8b00aef4d8537282f099';

function listUrl(...fields: string[]) {
  const selected = fields.length === 0
    ? ['started_at', 'status', 'metadata.invoked_by.email', 'metadata.boundary']
    : fields;
  return `/v1/sessions?${selected.map((field) => `fields=${field}`).join('&')}&page_size=25`;
}

const LIST_URL = listUrl();
const fetchMock = vi.fn<typeof fetch>();
const listRow = {
  session_id: SESSION_ID,
  started_at: summary.started_at,
  status: 'COMPLETED',
  metadata: { invoked_by: { email: 'operator@example.invalid' }, boundary: 'checkout' },
};

const receivedColumn: SessionColumn = {
  key: 'received_at', header: 'Received at', requiredFields: ['received_at'], renderCell: (row) => row.received_at,
};

function jsonResponse(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });
}

function rawResponse(text: string) {
  return new Response(text, { headers: { 'Content-Type': 'application/json' } });
}

function application(path = '/', columns: readonly SessionColumn[] = SESSION_COLUMNS) {
  return <MemoryRouter initialEntries={[path]}><App columns={columns} /></MemoryRouter>;
}

function deferredResponse() {
  let resolve!: (response: Response) => void;
  const promise = new Promise<Response>((done) => { resolve = done; });
  return { promise, resolve };
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal('fetch', fetchMock);
  window.getSelection()?.removeAllRanges();
});

describe('session table', () => {
  it('requests exactly the configured fields and renders the four columns in local time', async () => {
    fetchMock.mockResolvedValue(jsonResponse(page([listRow])));
    render(application());
    const table = await screen.findByRole('table');
    expect(within(table).getAllByRole('columnheader').map((cell) => cell.textContent)).toEqual([
      'Started at', 'Status', 'Invoked by', 'Boundary',
    ]);
    expect(within(table).getAllByRole('cell')).toHaveLength(4);
    expect(within(table).getByText('2026-10-01 14:37:04.000')).toBeInTheDocument();
    expect(within(table).getByText('2026-10-01 14:37:04.000').closest('time'))
      .toHaveAttribute('dateTime', '2026-10-01T09:07:04.000Z');
    expect(within(table).getByText('COMPLETED')).toBeInTheDocument();
    expect(within(table).getByText('operator@example.invalid')).toBeInTheDocument();
    expect(within(table).getByText('checkout')).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]?.[0]).toBe(LIST_URL);
  });

  it('names the browser time zone for the displayed times', async () => {
    fetchMock.mockResolvedValue(jsonResponse(page([listRow])));
    render(application());
    await screen.findByRole('table');
    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    expect(screen.getByText(`Open a session to inspect its execution record. Times are shown in ${zone}.`)).toBeInTheDocument();
  });

  it('renders a pending load followed by the empty state', async () => {
    const pending = deferredResponse();
    fetchMock.mockReturnValue(pending.promise);
    render(application());
    expect(screen.getByRole('status')).toHaveTextContent('Loading sessions');
    await act(async () => pending.resolve(jsonResponse(page([]))));
    expect(await screen.findByText('No sessions have been recorded yet.')).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('preserves row order and differentiates missing, null, zero, and structured values', async () => {
    const rows = [
      { session_id: OTHER_ID, metadata: { boundary: null } },
      { ...listRow, status: 'FAILED', metadata: { invoked_by: { email: 0 }, boundary: { nested: [false, 'text'] } } },
    ];
    fetchMock.mockResolvedValue(jsonResponse(page(rows)));
    render(application());
    const table = await screen.findByRole('table');
    const links = within(table).getAllByRole('link');
    expect(links.map((link) => link.getAttribute('href'))).toEqual([`/sessions/${OTHER_ID}`, `/sessions/${SESSION_ID}`]);
    const cells = within(table).getAllByRole('cell');
    expect(cells[0]).toHaveTextContent('Not provided');
    expect(cells[1]).toHaveTextContent('Not provided');
    expect(cells[2]).toHaveTextContent('Not provided');
    expect(cells[3]).toHaveTextContent('null');
    expect(cells[5]).toHaveTextContent('FAILED');
    expect(cells[6]).toHaveTextContent('0');
    expect(cells[7]).toHaveTextContent('"nested"');
    expect(cells[7]).toHaveTextContent('false');
  });

  it('changes requests and headers when code configuration adds or removes columns', async () => {
    fetchMock.mockImplementation(async () => jsonResponse(page([{ ...listRow, received_at: summary.received_at }])));
    const view = render(application());
    await screen.findByRole('table');
    view.rerender(application('/', [...SESSION_COLUMNS, receivedColumn]));
    await screen.findByRole('columnheader', { name: 'Received at' });
    expect(fetchMock.mock.lastCall?.[0]).toBe(
      listUrl('started_at', 'status', 'metadata.invoked_by.email', 'metadata.boundary', 'received_at'),
    );
    view.rerender(application('/', [receivedColumn]));
    const table = await screen.findByRole('table');
    expect(within(table).getAllByRole('columnheader')).toHaveLength(1);
    expect(fetchMock.mock.lastCall?.[0]).toBe(listUrl('received_at'));
    expect(within(table).getByRole('link')).toHaveTextContent(summary.received_at);
  });

  it('uses an explicit ID-only request for a column with no data dependencies', async () => {
    fetchMock.mockResolvedValue(jsonResponse(page([{ session_id: SESSION_ID }])));
    render(application('/', [{ key: 'record', header: 'Record', requiredFields: [], renderCell: () => 'Open' }]));
    await screen.findByRole('table');
    expect(fetchMock.mock.calls[0]?.[0]).toBe(listUrl('session_id'));
  });

  it('does not render inaccessible empty rows or fetch data with no configured columns', async () => {
    fetchMock.mockResolvedValue(jsonResponse(page([listRow])));
    const view = render(application('/', []));
    expect(screen.getByRole('alert')).toHaveTextContent('No session columns are configured.');
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
    view.rerender(application());
    expect(await screen.findByRole('table')).toBeInTheDocument();
  });

  it('does not refetch when a fresh column array has the same field dependencies', async () => {
    fetchMock.mockResolvedValue(jsonResponse(page([listRow])));
    const view = render(application());
    await screen.findByRole('table');
    view.rerender(application('/', SESSION_COLUMNS.map((column) => ({ ...column, header: `${column.header} label` }))));
    expect(screen.getByRole('columnheader', { name: 'Boundary label' })).toBeInTheDocument();
    expect(screen.getByRole('table')).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('renders markup in selected fields as text', async () => {
    const markup = '<img src=x onerror="alert(1)">';
    fetchMock.mockResolvedValue(jsonResponse(page([{
      ...listRow, metadata: { invoked_by: { email: markup }, boundary: '<script>x</script>' },
    }])));
    render(application());
    await screen.findByText(markup);
    expect(document.querySelector('img')).toBeNull();
    expect(document.querySelector('script')).toBeNull();
  });
});

describe('session navigation', () => {
  it('loads complete details on a row click, without using the partial list as detail', async () => {
    const user = userEvent.setup();
    fetchMock.mockImplementation(async (url) => url === LIST_URL ? jsonResponse(page([listRow])) : rawResponse(LARGE_DETAIL_JSON));
    render(application());
    await user.click(await screen.findByText('checkout'));
    expect(await screen.findByRole('heading', { name: 'Session details' })).toBeInTheDocument();
    expect(await screen.findByText('UNRECOGNIZED_VERDICT')).toBeInTheDocument();
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([LIST_URL, `/v1/sessions/${SESSION_ID}`]);
    expect(fetchMock.mock.calls[0]?.[1]?.signal?.aborted).toBe(true);
    await user.click(screen.getByText('Full session JSON', { selector: 'summary' }));
    const full = await screen.findByLabelText('Full session JSON', { selector: 'pre' });
    expect(full.textContent).toContain('"defect_count": 9223372036854775807');
    expect(full.textContent).toContain('"__proto__"');
    expect(full.textContent).toContain('"command": "actions-pairer"');
  });

  it('supports keyboard links without causing two detail requests', async () => {
    const user = userEvent.setup();
    fetchMock.mockImplementation(async (url) => url === LIST_URL
      ? jsonResponse(page([listRow]))
      : jsonResponse({ ...summary, metadata: {}, runs: [] }));
    render(application());
    const table = await screen.findByRole('table');
    const link = within(table).getByRole('link');
    link.focus();
    expect(link).toHaveFocus();
    await user.keyboard('{Enter}');
    await screen.findByText('No runs have been recorded for this session.');
    expect(fetchMock.mock.calls.filter(([url]) => url === `/v1/sessions/${SESSION_ID}`)).toHaveLength(1);
    await user.click(screen.getByRole('link', { name: '← All sessions' }));
    expect(await screen.findByRole('table')).toBeInTheDocument();
    expect(fetchMock.mock.lastCall?.[0]).toBe(LIST_URL);
  });

  it('keeps real hrefs for new-tab navigation and ignores modified row clicks', async () => {
    fetchMock.mockResolvedValue(jsonResponse(page([listRow])));
    render(application());
    const table = await screen.findByRole('table');
    expect(within(table).getByRole('link')).toHaveAttribute('href', `/sessions/${SESSION_ID}`);
    fireEvent.click(screen.getByText('checkout'), { ctrlKey: true });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('heading', { name: 'Sessions' })).toBeInTheDocument();
  });

  it('encodes a route parameter exactly once before requesting detail', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ error: { code: 'session_not_found', message: 'Session not found.' } }, 404));
    render(application('/sessions/%3Cscript%3E%3F%23'));
    await screen.findByRole('alert');
    expect(fetchMock.mock.calls[0]?.[0]).toBe('/v1/sessions/%3Cscript%3E%3F%23');
    expect(document.querySelector('script')).toBeNull();
  });

  it('supports browser history back navigation', async () => {
    const user = userEvent.setup();
    function BrowserControls() {
      const navigate = useNavigate();
      return <button onClick={() => { void navigate(-1); }}>Browser back</button>;
    }
    fetchMock.mockImplementation(async (url) => url === LIST_URL
      ? jsonResponse(page([listRow]))
      : jsonResponse({ ...summary, metadata: {}, runs: [] }));
    render(<MemoryRouter><BrowserControls /><App /></MemoryRouter>);
    await user.click(await screen.findByText('checkout'));
    await screen.findByText('No runs have been recorded for this session.');
    await user.click(screen.getByRole('button', { name: 'Browser back' }));
    expect(await screen.findByRole('table')).toBeInTheDocument();
  });

  it.each(['/unknown', '/ui/api/sessions', '/sessions/id/more', '/sessions/id/', '/Sessions/id'])(
    'does not fetch data for unknown UI route %s', (path) => {
      render(application(path));
      expect(screen.getByRole('heading', { name: 'Page not found' })).toBeInTheDocument();
      expect(fetchMock).not.toHaveBeenCalled();
    },
  );
});

describe('full session details', () => {
  it('displays root fields, exact outcomes, distinct identities, and all run fields', async () => {
    const user = userEvent.setup();
    fetchMock.mockResolvedValue(rawResponse(LARGE_DETAIL_JSON));
    render(application(`/sessions/${SESSION_ID}`));
    await screen.findByText('UNRECOGNIZED_VERDICT');
    expect(screen.getByText('Defects', { selector: 'dt' }).nextElementSibling).toHaveTextContent('9223372036854775807');
    expect(screen.getByText('Gaps', { selector: 'dt' }).nextElementSibling).toHaveTextContent('unknown');
    expect(screen.getByText('Contract ingredients', { selector: 'dt' }).nextElementSibling).toHaveTextContent('unknown');
    expect(screen.getByText('Recorded by', { selector: 'dt' }).nextElementSibling).toHaveTextContent('Agent');
    expect(screen.getByText('Invoked by', { selector: 'dt' }).nextElementSibling).toHaveTextContent('unverified');
    const runRegion = screen.getByRole('article', { name: `Run ${run.run_id}` });
    expect(within(runRegion).getByText('actions-pairer')).toBeInTheDocument();
    expect(within(runRegion).getByText(SESSION_ID)).toBeInTheDocument();
    expect(within(runRegion).getByText('2026-10-01 14:47:58.000')).toBeInTheDocument();
    expect(screen.getByText('pair-actions', { selector: 'li' }).querySelector('a')).toBeNull();
    await user.click(screen.getByText('Metadata JSON', { selector: 'summary' }));
    expect((await screen.findByLabelText('Metadata JSON', { selector: 'pre' })).textContent).toContain('<script>alert(1)</script>');
    expect(document.querySelector('script')).toBeNull();
    await user.click(screen.getByText(`Run details JSON — ${run.run_id}`, { selector: 'summary' }));
    expect((await screen.findByLabelText(`Run details JSON — ${run.run_id}`, { selector: 'pre' })).textContent).toContain('"large": 9223372036854775807');
    await user.click(screen.getByText('Execution outcome JSON', { selector: 'summary' }));
    expect((await screen.findByLabelText('Execution outcome JSON', { selector: 'pre' })).textContent).toContain('"minimum": -9223372036854775808');
  });

  it('does not compute missing outcome counts from runs and keeps zero distinct', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ ...summary, execution_outcome: { defect_count: 0 }, metadata: {}, runs: [run] }));
    render(application(`/sessions/${SESSION_ID}`));
    await screen.findByText(run.verdict);
    expect(screen.getByText('Defects', { selector: 'dt' }).nextElementSibling).toHaveTextContent(/^0$/);
    expect(screen.getByText('Gaps', { selector: 'dt' }).nextElementSibling).toHaveTextContent('unknown');
    expect(screen.getByText('Invoked by', { selector: 'dt' }).nextElementSibling).toHaveTextContent('Not provided');
    expect(screen.getByText('Recorded by', { selector: 'dt' }).nextElementSibling).toHaveTextContent('Not provided');
  });

  it('keeps run order and names without creating step links', async () => {
    const laterRun = { ...run, run_id: OTHER_ID, step: 'second-name', occurred_at: summary.started_at };
    fetchMock.mockResolvedValue(jsonResponse({ ...summary, metadata: {}, runs: [run, laterRun] }));
    render(application(`/sessions/${SESSION_ID}`));
    await screen.findByRole('article', { name: `Run ${OTHER_ID}` });
    expect(screen.getAllByRole('article').map((article) => article.getAttribute('aria-label'))).toEqual([`Run ${run.run_id}`, `Run ${OTHER_ID}`]);
  });
});

describe('request failures and lifecycle', () => {
  it.each(['/', `/sessions/${SESSION_ID}`])('shows an API error with its unchanged code at %s', async (path) => {
    fetchMock.mockResolvedValue(jsonResponse({ error: { code: 'session_not_found', message: 'Session not found.' } }, 404));
    render(application(path));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Session not found.');
    expect(alert).toHaveTextContent('session_not_found');
    expect(alert).toHaveTextContent('HTTP 404');
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it.each(['/', `/sessions/${SESSION_ID}`])('does not render an edge HTML error at %s', async (path) => {
    fetchMock.mockResolvedValue(new Response('<img src=x><p>private upstream error</p>', {
      status: 502, headers: { 'Content-Type': 'text/html' },
    }));
    render(application(path));
    expect(await screen.findByRole('alert')).toHaveTextContent('HTTP 502');
    expect(screen.queryByText('private upstream error')).not.toBeInTheDocument();
    expect(document.querySelector('img')).toBeNull();
  });

  it('shows network failure without raw error details or retries', async () => {
    fetchMock.mockRejectedValue(new TypeError('private connection details'));
    render(application());
    expect(await screen.findByRole('alert')).toHaveTextContent('Unable to reach the server.');
    expect(screen.queryByText('private connection details')).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it.each([
    page([{ session_id: SESSION_ID, started_at: 'bad timestamp' }]),
    [listRow],
    { ...page([listRow]), extra: 1 },
  ])('shows a malformed list response as an error instead of a broken table: %j', async (body) => {
    fetchMock.mockResolvedValue(jsonResponse(body));
    render(application());
    expect(await screen.findByRole('alert')).toHaveTextContent('The server returned an invalid response.');
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('sanitizes an unexpected loader rejection', async () => {
    const response = jsonResponse(page([]));
    vi.spyOn(response.headers, 'get').mockImplementation(() => { throw new Error('private implementation details'); });
    fetchMock.mockResolvedValue(response);
    render(application());
    expect(await screen.findByRole('alert')).toHaveTextContent('Unable to load this view.');
    expect(screen.queryByText('private implementation details')).not.toBeInTheDocument();
    expect(screen.queryByText(/HTTP/)).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('aborts an unmounted list and ignores its late result', async () => {
    const pending = deferredResponse();
    fetchMock.mockReturnValue(pending.promise);
    const view = render(application());
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const signal = fetchMock.mock.calls[0]?.[1]?.signal;
    view.unmount();
    expect(signal?.aborted).toBe(true);
    await act(async () => pending.resolve(jsonResponse(page([listRow]))));
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('does not replace a new session with a late response for the old session', async () => {
    const user = userEvent.setup();
    const old = deferredResponse();
    fetchMock.mockImplementation(async (url) => url === `/v1/sessions/${SESSION_ID}`
      ? old.promise : jsonResponse({ ...summary, session_id: OTHER_ID, metadata: {}, runs: [] }));
    render(<MemoryRouter initialEntries={[`/sessions/${SESSION_ID}`]}>
      <Link to={`/sessions/${OTHER_ID}`}>Switch session</Link><App />
    </MemoryRouter>);
    expect(screen.getByRole('status')).toHaveTextContent('Loading session');
    await user.click(screen.getByRole('link', { name: 'Switch session' }));
    await screen.findByText(OTHER_ID);
    expect(fetchMock.mock.calls[0]?.[1]?.signal?.aborted).toBe(true);
    await act(async () => old.resolve(jsonResponse({ ...summary, metadata: {}, runs: [] })));
    expect(within(screen.getByRole('region', { name: 'Session' })).getByText(OTHER_ID)).toBeInTheDocument();
    expect(screen.queryByText(SESSION_ID)).not.toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('discards the old projection while a new column configuration loads', async () => {
    const pending = deferredResponse();
    fetchMock.mockResolvedValueOnce(jsonResponse(page([listRow]))).mockReturnValueOnce(pending.promise);
    const view = render(application());
    await screen.findByText('checkout');
    view.rerender(application('/', [receivedColumn]));
    expect(screen.queryByText('checkout')).not.toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('Loading sessions');
    await act(async () => pending.resolve(jsonResponse(page([{ session_id: SESSION_ID, received_at: summary.received_at }]))));
    expect(await screen.findByRole('link', { name: new RegExp(summary.received_at) })).toBeInTheDocument();
  });

  it('handles StrictMode setup/cleanup without displaying cancellation as an error', async () => {
    fetchMock.mockImplementation(async () => jsonResponse(page([listRow])));
    render(<StrictMode>{application()}</StrictMode>);
    expect(await screen.findByRole('table')).toBeInTheDocument();
    expect(fetchMock.mock.calls[0]?.[1]?.signal?.aborted).toBe(true);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});
