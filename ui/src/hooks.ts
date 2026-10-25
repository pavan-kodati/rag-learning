import { useCallback, useEffect, useRef, useState } from "react";
import { describeError } from "./api";

export interface AsyncState<T> { data: T | null; error: string | null; loading: boolean; reload: () => void }

/** Runs `fn` when `deps` change; ignores results from superseded calls. */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[], enabled = true): AsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(enabled);
  const run = useRef(0);
  const fnRef = useRef(fn);
  fnRef.current = fn;

  const load = useCallback(() => {
    const id = ++run.current;
    setLoading(true);
    setError(null);
    fnRef.current().then(
      (d) => { if (id === run.current) { setData(d); setLoading(false); } },
      (e) => { if (id === run.current) { setError(describeError(e)); setLoading(false); } },
    );
  }, []);

  useEffect(() => {
    if (!enabled) { setLoading(false); return; }
    load();
    const counter = run;
    return () => { counter.current++; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, enabled]);

  return { data, error, loading, reload: load };
}

export function usePoll(fn: () => Promise<boolean>, intervalMs: number, active: boolean): void {
  const fnRef = useRef(fn);
  fnRef.current = fn;
  useEffect(() => {
    if (!active) return;
    let stop = false;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      try {
        const done = await fnRef.current();
        if (done || stop) return;
      } catch { /* keep polling; the next tick may succeed */ }
      timer = setTimeout(tick, intervalMs);
    };
    timer = setTimeout(tick, intervalMs);
    return () => { stop = true; clearTimeout(timer); };
  }, [active, intervalMs]);
}
