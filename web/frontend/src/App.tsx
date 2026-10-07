import { Link, Route, Routes, useLocation } from 'react-router-dom';

import { SessionDetail } from './SessionDetail';
import { SessionList } from './SessionList';
import { SESSION_COLUMNS } from './sessionColumns';
import type { SessionColumn } from './sessionColumns';

export function App({ columns = SESSION_COLUMNS }: { columns?: readonly SessionColumn[] }) {
  const { pathname } = useLocation();
  // React Router tolerates trailing slashes; match the webserver's exact UI paths.
  const knownPath = pathname === '/' || /^\/sessions\/[^/]+$/.test(pathname);
  return (
    <>
      <a className="skip-link" href="#main">Skip to content</a>
      <header className="app-header"><Link to="/" className="brand">Quality agent</Link><span>Execution records</span></header>
      <main id="main" className="app-main" tabIndex={-1}>
        {knownPath
          ? <Routes>
              <Route path="/" caseSensitive element={<SessionList columns={columns} />} />
              <Route path="/sessions/:sessionId" caseSensitive element={<SessionDetail />} />
            </Routes>
          : <section className="page-heading"><h1>Page not found</h1><Link to="/">Return to sessions</Link></section>}
      </main>
    </>
  );
}
