import { serverNow } from "../../../api/live";
import { cn } from "../../../components";
import { useNow } from "../../../lib/useNow";
import { mss } from "../../../lib/format";

/** Seconds since `since` on the server's clock (0 before it). */
export function elapsedSeconds(since: string | null | undefined, now: number): number {
  if (!since) return 0;
  const t = Date.parse(since);
  return Number.isNaN(t) ? 0 : Math.max(0, Math.floor((now - t) / 1_000));
}

/** "2:14" counting up from when the call was answered; "Ringing" before that. */
export function LiveDuration({ since, className }: { since: string | null | undefined; className?: string }) {
  const tick = useNow(Boolean(since));
  if (!since) return <span className={cn("text-fg-3", className)}>Ringing</span>;
  const s = elapsedSeconds(since, tick + (serverNow() - Date.now()));
  return <span className={cn("font-mono tnum", className)}>{mss(s)}</span>;
}
