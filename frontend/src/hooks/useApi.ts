import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "@/api/client";
import type { ApiEnvelope } from "@/types/api";

interface UseApiState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
}

/** Fetches once (or whenever `deps` change), tracking loading/error/data. */
export function useApi<T>(fetcher: () => Promise<ApiEnvelope<T>>, deps: unknown[] = []): UseApiState<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetcherRef
      .current()
      .then((res) => {
        if (!cancelled) setData(res.data);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof ApiError ? e.message : "Something went wrong. Please try again.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  const reload = useCallback(() => setTick((t) => t + 1), []);

  return { data, loading, error, reload };
}
