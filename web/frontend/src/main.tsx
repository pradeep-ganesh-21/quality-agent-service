import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

const root = document.getElementById('root');
if (root === null) {
  throw new Error('The frontend root element is missing.');
}

createRoot(root).render(
  <StrictMode>
    <main>
      <h1>Quality agent</h1>
      <p>The frontend foundation is ready. Session views are not implemented yet.</p>
    </main>
  </StrictMode>,
);
