import { talkMinutes, useStackRate } from "../api/pricing";
import { Skeleton } from "./Skeleton";

/** Whole minutes of calls `micros` pays for on the default stack at the served price; a short placeholder while the price loads. */
export function TalkMinutes({ micros }: { micros: bigint }) {
  const rate = useStackRate();
  if (rate === undefined) return <Skeleton className="inline-block h-[1em] w-[3ch] align-middle" />;
  return <>{talkMinutes(micros, rate)}</>;
}
