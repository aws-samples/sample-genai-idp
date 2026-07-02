// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
//
// Lightweight polling hook used to replace AppSync GraphQL subscriptions under
// the HTTP API transport (AppSync is unavailable in GovCloud / not FedRAMP).
//
// Behavior:
//   - Runs `callback` every `intervalMs` while `enabled` is true.
//   - Pauses while the browser tab is hidden (document.visibilitychange) and
//     fires immediately when the tab becomes visible again, to cut cost without
//     stalling updates the user is looking at.
//   - Does NOT fire an initial call on mount by default (set `immediate` to
//     fire once right away).
//
// The callback is held in a ref so changing its identity does not restart the
// interval (avoids tearing down/recreating timers on every render).
import { useEffect, useRef } from 'react';

interface UsePollingOptions {
  enabled: boolean;
  intervalMs: number;
  immediate?: boolean;
}

export const usePolling = (callback: () => void | Promise<void>, { enabled, intervalMs, immediate = false }: UsePollingOptions): void => {
  const savedCallback = useRef(callback);
  useEffect(() => {
    savedCallback.current = callback;
  }, [callback]);

  useEffect(() => {
    if (!enabled) return undefined;

    let timer: ReturnType<typeof setInterval> | null = null;

    const tick = () => {
      // Skip work while hidden; the visibility handler resumes it.
      if (document.visibilityState === 'hidden') return;
      void savedCallback.current();
    };

    const start = () => {
      if (timer == null) {
        timer = setInterval(tick, intervalMs);
      }
    };
    const stop = () => {
      if (timer != null) {
        clearInterval(timer);
        timer = null;
      }
    };

    const onVisibility = () => {
      if (document.visibilityState === 'visible') {
        void savedCallback.current(); // fire immediately on resume
        start();
      } else {
        stop();
      }
    };

    if (immediate) {
      void savedCallback.current();
    }
    start();
    document.addEventListener('visibilitychange', onVisibility);

    return () => {
      stop();
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [enabled, intervalMs, immediate]);
};

export default usePolling;
