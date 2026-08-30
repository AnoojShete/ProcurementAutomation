import { useCallback, useRef, useState } from "react";

interface PollOptions<T> {
  intervalMs?: number;
  maxAttempts?: number;
  /** Return true once `result` reflects the settled state you're waiting for. */
  isSettled: (result: T) => boolean;
}

type PollState = "idle" | "polling" | "settled" | "timed-out" | "error";

/**
 * Used for backend actions that return before the real state change lands
 * (e.g. POST /requests/{id}/approve signals a Temporal workflow; the status
 * flips a moment later in a separate worker). Never trust the immediate
 * response — poll the read endpoint until it reflects the change.
 */
export function usePolling<T>() {
  const [state, setState] = useState<PollState>("idle");
  const [result, setResult] = useState<T | null>(null);
  const cancelledRef = useRef(false);

  const run = useCallback(async (fetchLatest: () => Promise<T>, opts: PollOptions<T>) => {
    const { intervalMs = 700, maxAttempts = 10, isSettled } = opts;
    cancelledRef.current = false;
    setState("polling");
    for (let attempt = 0; attempt < maxAttempts; attempt++) {
      if (cancelledRef.current) return;
      try {
        const latest = await fetchLatest();
        if (isSettled(latest)) {
          setResult(latest);
          setState("settled");
          return latest;
        }
        setResult(latest);
      } catch {
        setState("error");
        return null;
      }
      await new Promise((r) => setTimeout(r, intervalMs));
    }
    setState("timed-out");
    return null;
  }, []);

  const cancel = useCallback(() => {
    cancelledRef.current = true;
  }, []);

  return { state, result, run, cancel };
}
