import { useEffect, useRef } from "react";

interface SingleFlightPollingOptions {
  enabled: boolean;
  identity: string;
  intervalMs: number;
  poll: (signal: AbortSignal) => Promise<void>;
}

export function useSingleFlightPolling({ enabled, identity, intervalMs, poll }: SingleFlightPollingOptions) {
  const pollRef = useRef(poll);
  pollRef.current = poll;

  useEffect(() => {
    if (!enabled) {
      return;
    }

    let stopped = false;
    let timeoutId: number | undefined;
    let controller: AbortController | undefined;

    const schedule = () => {
      timeoutId = window.setTimeout(run, intervalMs);
    };

    const run = async () => {
      controller = new AbortController();
      try {
        await pollRef.current(controller.signal);
      } catch {
        // Poll callbacks own user-visible error handling; this prevents rejected
        // timer promises from becoming unhandled browser errors.
      } finally {
        controller = undefined;
        if (!stopped) {
          schedule();
        }
      }
    };

    schedule();
    return () => {
      stopped = true;
      if (timeoutId !== undefined) {
        window.clearTimeout(timeoutId);
      }
      controller?.abort();
    };
  }, [enabled, identity, intervalMs]);
}
