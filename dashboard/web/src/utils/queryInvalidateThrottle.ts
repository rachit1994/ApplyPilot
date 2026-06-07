/** Coalesce bursty invalidate/refetch triggers (e.g. SSE ticks) to at most once per window. */
export function createInvalidateThrottle(minMs: number): (fn: () => void) => void {
  let last = 0;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let pending: (() => void) | null = null;

  return (fn: () => void) => {
    const now = Date.now();
    const elapsed = now - last;

    const run = () => {
      last = Date.now();
      fn();
    };

    if (elapsed >= minMs) {
      if (timer) {
        clearTimeout(timer);
        timer = null;
      }
      pending = null;
      run();
      return;
    }

    pending = fn;
    if (timer) return;
    timer = setTimeout(() => {
      timer = null;
      pending?.();
      pending = null;
      last = Date.now();
    }, minMs - elapsed);
  };
}
