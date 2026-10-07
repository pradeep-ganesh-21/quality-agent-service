import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { App } from '../src/App';
import { page, SESSION_ID, summary } from './fixtures';

const OTHER_ID = '68df8b00aef4d8537282f099';
const FIELDS = 'fields=started_at&fields=status&fields=metadata.invoked_by.email&fields=metadata.boundary';
const fetchMock = vi.fn<typeof fetch>();

const listRow = {
  session_id: SESSION_ID,
  started_at: summary.started_at,
  status: 'COMPLETED',
  metadata: { invoked_by: { email: 'operator@example.invalid' }, boundary: 'checkout' },
};

function jsonResponse(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });
}

// Each call needs its own Response: a body can only be read once.
function respondWith(value: unknown, status = 200) {
  fetchMock.mockImplementation(async () => jsonResponse(value, status));
}

function CurrentUrl() {
  const { pathname, search } = useLocation();
  return <p data-testid="url">{`${pathname}${search}`}</p>;
}

function BrowserControls() {
  const navigate = useNavigate();
  return (
    <>
      <button onClick={() => { void navigate(-1); }}>Browser back</button>
      <button onClick={() => { void navigate(1); }}>Browser forward</button>
    </>
  );
}

function application(path = '/') {
  return (
    <MemoryRouter initialEntries={[path]}>
      <BrowserControls /><CurrentUrl /><App />
    </MemoryRouter>
  );
}

function requestedUrls() {
  return fetchMock.mock.calls.map(([url]) => String(url));
}

function currentUrl() {
  return screen.getByTestId('url').textContent;
}

async function openFilters(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: /^Filters/ }));
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal('fetch', fetchMock);
  respondWith(page([listRow], { total_count: 1 }));
});

describe('filter panel', () => {
  it('stays closed with no applied filters and opens on request', async () => {
    const user = userEvent.setup();
    render(application());
    await screen.findByRole('table');
    const toggle = screen.getByRole('button', { name: 'Filters' });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByRole('button', { name: 'Apply filters' })).not.toBeInTheDocument();

    await user.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('combobox', { name: 'Status' })).toHaveValue('');
    expect(screen.getByRole('textbox', { name: 'Boundary' })).toHaveValue('');
  });

  it('does not request anything until the draft is submitted', async () => {
    const user = userEvent.setup();
    render(application());
    await screen.findByRole('table');
    await openFilters(user);

    await user.type(screen.getByRole('textbox', { name: 'Boundary' }), 'checkout');
    await user.selectOptions(screen.getByRole('combobox', { name: 'Status' }), 'FAILED');
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(currentUrl()).toBe('/');

    await user.click(screen.getByRole('button', { name: 'Apply filters' }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(currentUrl()).toBe('/?status=FAILED&boundary=checkout');
    expect(requestedUrls()[1]).toBe(`/v1/sessions?${FIELDS}&status=FAILED&boundary=checkout&page_size=25`);
  });

  it('submits the draft when Enter is pressed in a text field', async () => {
    const user = userEvent.setup();
    render(application());
    await screen.findByRole('table');
    await openFilters(user);

    await user.type(screen.getByRole('textbox', { name: 'Invoked by email' }), 'Operator@Example.invalid{Enter}');
    await waitFor(() => expect(currentUrl()).toBe('/?invoked_by_email=Operator%40Example.invalid'));
    // The address is matched exactly, so its case must survive untouched.
    expect(requestedUrls()[1]).toBe(`/v1/sessions?${FIELDS}&invoked_by_email=Operator%40Example.invalid&page_size=25`);
  });

  it('converts local date bounds to UTC instants', async () => {
    const user = userEvent.setup();
    render(application());
    await screen.findByRole('table');
    await openFilters(user);

    await user.type(screen.getByLabelText('Started from'), '2026-10-01T09:07:00');
    await user.click(screen.getByRole('button', { name: 'Apply filters' }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(requestedUrls()[1]).toBe(
      `/v1/sessions?${FIELDS}&started_from=2026-10-01T03%3A37%3A00.000Z&page_size=25`,
    );
  });

  it('reports an inverted range without requesting anything', async () => {
    const user = userEvent.setup();
    render(application());
    await screen.findByRole('table');
    await openFilters(user);

    await user.type(screen.getByLabelText('Started from'), '2026-10-02T09:07:00');
    await user.type(screen.getByLabelText('Started before'), '2026-10-01T09:07:00');
    await user.click(screen.getByRole('button', { name: 'Apply filters' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Started from must be earlier than started before.');
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(currentUrl()).toBe('/');
  });

  it('keeps the applied filters, shows a count, and preserves drafts while hidden', async () => {
    const user = userEvent.setup();
    render(application('/?status=FAILED&boundary=checkout'));
    await screen.findByRole('table');

    const toggle = screen.getByRole('button', { name: 'Filters (2)' });
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('combobox', { name: 'Status' })).toHaveValue('FAILED');
    expect(screen.getByRole('textbox', { name: 'Boundary' })).toHaveValue('checkout');

    await user.clear(screen.getByRole('textbox', { name: 'Boundary' }));
    await user.type(screen.getByRole('textbox', { name: 'Boundary' }), 'payments');
    await user.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    await user.click(toggle);
    expect(screen.getByRole('textbox', { name: 'Boundary' })).toHaveValue('payments');
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('clears every filter and returns to the newest page while keeping the page size', async () => {
    const user = userEvent.setup();
    render(application('/?status=FAILED&boundary=checkout&page_size=50&cursor=djF8bmV4dHwx'));
    await screen.findByRole('table');

    await user.click(screen.getByRole('button', { name: 'Clear filters' }));
    await waitFor(() => expect(currentUrl()).toBe('/?page_size=50'));
    expect(requestedUrls().at(-1)).toBe(`/v1/sessions?${FIELDS}&page_size=50`);
    expect(screen.getByRole('combobox', { name: 'Status' })).toHaveValue('');
    expect(screen.getByRole('button', { name: 'Filters' })).toBeInTheDocument();
  });

  it('omits whitespace-only text and keeps surrounding spaces in a real value', async () => {
    const user = userEvent.setup();
    render(application());
    await screen.findByRole('table');
    await openFilters(user);

    await user.type(screen.getByRole('textbox', { name: 'Boundary' }), '   ');
    await user.click(screen.getByRole('button', { name: 'Apply filters' }));
    await waitFor(() => expect(currentUrl()).toBe('/'));

    await user.clear(screen.getByRole('textbox', { name: 'Boundary' }));
    await user.type(screen.getByRole('textbox', { name: 'Boundary' }), ' check out ');
    await user.click(screen.getByRole('button', { name: 'Apply filters' }));
    await waitFor(() => expect(requestedUrls().at(-1)).toBe(
      `/v1/sessions?${FIELDS}&boundary=+check+out+&page_size=25`,
    ));
  });
});

describe('restored links', () => {
  it('requests the filters, page size, and cursor from the URL', async () => {
    render(application('/?status=COMPLETED&started_before=2026-10-02T03:37:00.000Z&page_size=100&cursor=djF8bmV4dHwx'));
    await screen.findByRole('table');
    expect(requestedUrls()[0]).toBe(
      `/v1/sessions?${FIELDS}&status=COMPLETED&started_before=2026-10-02T03%3A37%3A00.000Z`
      + '&page_size=100&cursor=djF8bmV4dHwx',
    );
    expect(screen.getByLabelText('Started before')).toHaveValue('2026-10-02T09:07');
    expect(screen.getByRole('combobox', { name: 'Rows per page' })).toHaveValue('100');
  });

  it('re-applying a restored link does not shift its instant', async () => {
    const user = userEvent.setup();
    render(application('/?started_from=2026-10-01T03:37:04.123Z'));
    await screen.findByRole('table');
    expect(screen.getByLabelText('Started from')).toHaveValue('2026-10-01T09:07:04.123');

    await user.click(screen.getByRole('button', { name: 'Apply filters' }));
    // The instant is unchanged, so the view neither moves nor re-reads.
    await waitFor(() => expect(currentUrl()).toBe('/?started_from=2026-10-01T03:37:04.123Z'));
    expect(requestedUrls()).toEqual([
      `/v1/sessions?${FIELDS}&started_from=2026-10-01T03%3A37%3A04.123Z&page_size=25`,
    ]);
  });

  it.each([
    ['/?sort=started_at', 'This link uses a filter this page does not support.'],
    ['/?status=DONE', 'This link uses an unknown status filter.'],
    ['/?page_size=10', 'This link uses a page size this page does not offer.'],
    ['/?started_from=yesterday', 'Started from is not a valid date and time.'],
    ['/?status=FAILED&status=COMPLETED', 'This link repeats a filter.'],
  ])('rejects %s without requesting a wider page', async (path, message) => {
    render(application(path));
    expect(await screen.findByRole('alert')).toHaveTextContent(message);
    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    // The form stays available so the filters can be corrected.
    expect(screen.getByRole('button', { name: 'Apply filters' })).toBeInTheDocument();
  });

  it('recovers from a rejected link once the filters are cleared', async () => {
    const user = userEvent.setup();
    render(application('/?status=DONE'));
    await screen.findByRole('alert');
    await user.click(screen.getByRole('button', { name: 'Clear filters' }));
    expect(await screen.findByRole('table')).toBeInTheDocument();
    expect(requestedUrls()).toEqual([`/v1/sessions?${FIELDS}&page_size=25`]);
  });
});

describe('pagination', () => {
  it('follows the returned cursors and keeps the applied filters', async () => {
    const user = userEvent.setup();
    respondWith(page([listRow], {
      total_count: 318, next_cursor: 'djF8bmV4dHwx', previous_cursor: 'djF8cHJldnwx',
    }));
    render(application('/?status=COMPLETED'));
    await screen.findByRole('table');

    await user.click(screen.getByRole('button', { name: 'Next' }));
    await waitFor(() => expect(currentUrl()).toBe('/?status=COMPLETED&cursor=djF8bmV4dHwx'));
    expect(requestedUrls().at(-1)).toBe(
      `/v1/sessions?${FIELDS}&status=COMPLETED&page_size=25&cursor=djF8bmV4dHwx`,
    );

    await waitFor(() => expect(screen.getByRole('button', { name: 'Previous' })).toBeEnabled());
    await user.click(screen.getByRole('button', { name: 'Previous' }));
    await waitFor(() => expect(currentUrl()).toBe('/?status=COMPLETED&cursor=djF8cHJldnwx'));
  });

  it('disables navigation in a direction the response reports as exhausted', async () => {
    respondWith(page([listRow], { total_count: 1 }));
    render(application());
    await screen.findByRole('table');
    expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Previous' })).toBeDisabled();
  });

  it('uses the applied filters for the next page even when the draft has unsubmitted edits', async () => {
    const user = userEvent.setup();
    respondWith(page([listRow], { total_count: 318, next_cursor: 'djF8bmV4dHwx' }));
    render(application('/?status=COMPLETED'));
    await screen.findByRole('table');

    await user.type(screen.getByRole('textbox', { name: 'Boundary' }), 'payments');
    await user.click(screen.getByRole('button', { name: 'Next' }));
    await waitFor(() => expect(requestedUrls().at(-1)).toBe(
      `/v1/sessions?${FIELDS}&status=COMPLETED&page_size=25&cursor=djF8bmV4dHwx`,
    ));
    expect(screen.getByRole('textbox', { name: 'Boundary' })).toHaveValue('payments');
  });

  it('drops the cursor when the page size changes', async () => {
    const user = userEvent.setup();
    render(application('/?cursor=djF8bmV4dHwx'));
    await screen.findByRole('table');

    await user.selectOptions(screen.getByRole('combobox', { name: 'Rows per page' }), '50');
    await waitFor(() => expect(currentUrl()).toBe('/?page_size=50'));
    expect(requestedUrls().at(-1)).toBe(`/v1/sessions?${FIELDS}&page_size=50`);
  });

  it('reports the page and the live match count', async () => {
    respondWith(page([listRow, { ...listRow, session_id: OTHER_ID }], {
      total_count: 318, next_cursor: 'djF8bmV4dHwx',
    }));
    render(application());
    await screen.findByRole('table');
    expect(screen.getByText('2 sessions on this page · 318 sessions recorded')).toBeInTheDocument();
  });

  it('describes the count as a filtered match when a filter is applied', async () => {
    respondWith(page([listRow], { total_count: 1 }));
    render(application('/?status=COMPLETED'));
    await screen.findByRole('table');
    expect(screen.getByText('1 session on this page · 1 session matching these filters')).toBeInTheDocument();
  });
});

describe('empty results', () => {
  it('separates an empty database from an empty filter result', async () => {
    const user = userEvent.setup();
    respondWith(page([]));
    render(application());
    expect(await screen.findByText('No sessions have been recorded yet.')).toBeInTheDocument();

    await openFilters(user);
    await user.selectOptions(screen.getByRole('combobox', { name: 'Status' }), 'FAILED');
    await user.click(screen.getByRole('button', { name: 'Apply filters' }));
    expect(await screen.findByText('No sessions match these filters.')).toBeInTheDocument();
  });

  it('offers a return to the newest page when a cursor outlives its records', async () => {
    const user = userEvent.setup();
    respondWith(page([], { total_count: 318 }));
    render(application('/?cursor=djF8bmV4dHwx'));
    expect(await screen.findByText(/This page has no sessions/)).toBeInTheDocument();
    expect(screen.getByText('0 sessions on this page · 318 sessions recorded')).toBeInTheDocument();

    respondWith(page([listRow], { total_count: 318 }));
    await user.click(screen.getByRole('button', { name: 'Return to newest sessions' }));
    await waitFor(() => expect(currentUrl()).toBe('/'));
    expect(await screen.findByRole('table')).toBeInTheDocument();
  });
});

describe('history and detail navigation', () => {
  it('restores applied filters and inputs with browser back and forward', async () => {
    const user = userEvent.setup();
    render(application());
    await screen.findByRole('table');
    await openFilters(user);

    await user.selectOptions(screen.getByRole('combobox', { name: 'Status' }), 'FAILED');
    await user.click(screen.getByRole('button', { name: 'Apply filters' }));
    await waitFor(() => expect(currentUrl()).toBe('/?status=FAILED'));

    await user.click(screen.getByRole('button', { name: 'Browser back' }));
    await waitFor(() => expect(currentUrl()).toBe('/'));
    expect(screen.getByRole('combobox', { name: 'Status' })).toHaveValue('');

    await user.click(screen.getByRole('button', { name: 'Browser forward' }));
    await waitFor(() => expect(currentUrl()).toBe('/?status=FAILED'));
    expect(screen.getByRole('combobox', { name: 'Status' })).toHaveValue('FAILED');
    expect(requestedUrls().at(-1)).toBe(`/v1/sessions?${FIELDS}&status=FAILED&page_size=25`);
  });

  it('returns from a session to the same filtered page', async () => {
    const user = userEvent.setup();
    fetchMock.mockImplementation(async (url) => String(url).startsWith('/v1/sessions/')
      ? jsonResponse({ ...summary, metadata: {}, runs: [] })
      : jsonResponse(page([listRow], { total_count: 318, next_cursor: 'djF8bmV4dHwx' })));
    render(application('/?status=COMPLETED&page_size=50'));
    await screen.findByRole('table');

    await user.click(within(screen.getByRole('table')).getByRole('link'));
    await screen.findByRole('heading', { name: 'Session details' });

    await user.click(screen.getByRole('link', { name: '← All sessions' }));
    await waitFor(() => expect(currentUrl()).toBe('/?status=COMPLETED&page_size=50'));
    expect(screen.getByRole('combobox', { name: 'Status' })).toHaveValue('COMPLETED');
  });

  it('returns to the newest page when a session is opened directly', async () => {
    const user = userEvent.setup();
    respondWith({ ...summary, metadata: {}, runs: [] });
    render(application(`/sessions/${SESSION_ID}`));
    await screen.findByRole('heading', { name: 'Session details' });
    expect(screen.getByRole('link', { name: '← All sessions' })).toHaveAttribute('href', '/');

    respondWith(page([listRow], { total_count: 1 }));
    await user.click(screen.getByRole('link', { name: '← All sessions' }));
    await act(async () => { await Promise.resolve(); });
    expect(await screen.findByRole('table')).toBeInTheDocument();
  });
});
