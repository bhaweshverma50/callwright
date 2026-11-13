import { useCallback, useEffect, useState } from "react";

/** Seconds left on a resend cooldown; `restart` starts it again (after each send). */
export function useCooldown(seconds: number) {
  const [until, setUntil] = useState(0);
  const [now, setNow] = useState(() => Date.now());
  const left = Math.max(0, Math.ceil((until - now) / 1000));

  // Ticks from the deadline, not by counting: a throttled background tab still ends on time.
  useEffect(() => {
    if (until <= Date.now()) return;
    const t = window.setInterval(() => {
      setNow(Date.now());
      if (Date.now() >= until) window.clearInterval(t);
    }, 1000);
    return () => window.clearInterval(t);
  }, [until]);

  const restart = useCallback(() => {
    const t = Date.now();
    setNow(t);
    setUntil(t + seconds * 1000);
  }, [seconds]);

  return { left, restart };
}

/** "0:42" for a countdown label. */
export function mmss(total: number): string {
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}
