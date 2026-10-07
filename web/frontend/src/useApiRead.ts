import { useEffect, useEffectEvent, useState } from 'react';

import type { ApiFailure, ApiResult } from './types';

export type ReadFailure = Exclude<ApiFailure, { kind: 'cancelled' }>
  | { kind: 'unexpected'; message: string };

type ReadState<T> =
  | { status: 'loading' }
  | { status: 'ready'; data: T }
  | { status: 'error'; error: ReadFailure };

export function useApiRead<T>(
  requestKey: string,
  load: (signal: AbortSignal) => Promise<ApiResult<T>>,
): ReadState<T> {
  const [snapshot, setSnapshot] = useState<{ key: string; state: ReadState<T> } | null>(null);
  // All request inputs belong in requestKey. Callback identity alone is not a new read.
  const loadCurrent = useEffectEvent(load);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setSnapshot({ key: requestKey, state: { status: 'loading' } });

    async function read() {
      let result: ApiResult<T>;
      try {
        result = await loadCurrent(controller.signal);
      } catch {
        // Unexpected loader failures must not expose exception text to the page.
        if (active) setSnapshot({ key: requestKey, state: {
          status: 'error', error: { kind: 'unexpected', message: 'Unable to load this view.' },
        } });
        return;
      }
      if (!active) return;
      if (result.ok) {
        setSnapshot({ key: requestKey, state: { status: 'ready', data: result.data } });
      } else if (result.error.kind !== 'cancelled') {
        setSnapshot({ key: requestKey, state: { status: 'error', error: result.error } });
      }
    }

    void read();
    return () => {
      active = false;
      controller.abort();
    };
  }, [requestKey]);

  // Effects run after render: never show the previous request's data in between.
  return snapshot?.key === requestKey ? snapshot.state : { status: 'loading' };
}
