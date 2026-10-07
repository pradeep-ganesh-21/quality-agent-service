import type { ReadFailure } from './useApiRead';

export function LoadingNotice({ children }: { children: string }) {
  return <p className="notice" role="status">{children}</p>;
}

export function ErrorNotice({ error }: { error: ReadFailure }) {
  return (
    <div className="notice notice-error" role="alert">
      <p>{error.message}</p>
      {'status' in error && <p className="notice-detail">HTTP {error.status}</p>}
      {error.kind === 'api' && <p className="notice-detail"><code>{error.code}</code></p>}
    </div>
  );
}
