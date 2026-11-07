import { CalendarClock, Layers, TriangleAlert } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import { useId } from "react";
import { useQuote, useRecentTransactions } from "../../api/queries";
import type { Transaction } from "../../api/types";
import { InfoTip, MoneyText, Skeleton, Ticker, cn } from "../../components";
import { formatUsd, LOW_BALANCE_MICROS, toMicros } from "../../lib/money";
import { DEFAULT_STACK, talkMinutes } from "../../api/pricing";

const DAY_MS = 86_400_000;
export const SPEND_WINDOW_DAYS = 14;

export interface TalkTimeFacts {
  minutes: number;
  /** Balance as a share of the highest balance in the last 30 days (0 to 1). */
  fill: number;
  peakMicros: bigint;
  /** Average daily spend over the last 14 days, in micro-dollars; 0 when nothing was spent. */
  perDayMicros: bigint;
  /** When the balance runs out at that pace; null when there was no spend. */
  runOut: Date | null;
}

/** Talk time, gauge fill and projected run-out from the balance, stack price and recent ledger rows. */
export function talkTimeFacts(balanceMicros: bigint, perMinuteMicros: bigint, txns: Transaction[], now = new Date()): TalkTimeFacts {
  const since30 = now.getTime() - 30 * DAY_MS;
  const sinceSpend = now.getTime() - SPEND_WINDOW_DAYS * DAY_MS;
  let peak = balanceMicros;
  let spent = 0n;
  for (const t of txns) {
    const at = Date.parse(t.created_at);
    if (at >= since30) {
      const after = toMicros(t.balance_after_usd) ?? 0n;
      if (after > peak) peak = after;
    }
    if (at >= sinceSpend && (t.type === "call_charge" || t.type === "feature_charge")) {
      spent += -(toMicros(t.amount_usd) ?? 0n);
    }
  }
  const perDay = spent > 0n ? spent / BigInt(SPEND_WINDOW_DAYS) : 0n;
  const runOut = perDay > 0n && balanceMicros > 0n ? new Date(now.getTime() + Number((balanceMicros * BigInt(DAY_MS)) / perDay)) : null;
  const fill = peak > 0n && balanceMicros > 0n ? Math.min(1, Number((balanceMicros * 10_000n) / peak) / 10_000) : 0;
  return { minutes: talkMinutes(balanceMicros, perMinuteMicros), fill, peakMicros: peak, perDayMicros: perDay, runOut };
}

const dateFmt = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short" });

/**
 * Billing signature moment (docs/DESIGN.md section 6): the balance as talk time. The arc animates
 * to the balance against its recent peak; the big figure is minutes of calls on the workspace's
 * default stack, priced by the quote endpoint; the run-out date comes from the last 14 days of spend.
 */
export function TalkTimeGauge({ balanceUsd, loading }: { balanceUsd: string | undefined; loading: boolean }) {
  const quote = useQuote({ components: DEFAULT_STACK });
  const recent = useRecentTransactions();
  const perMinute = quote.data ? toMicros(quote.data.per_minute_total_usd) : null;
  const name = (c: "stt" | "llm" | "tts") => quote.data?.lines.find((l) => l.component === c)?.label ?? DEFAULT_STACK[c].model;
  const balance = balanceUsd ? toMicros(balanceUsd) : null;
  const ready = balance !== null && perMinute !== null && recent.data;
  const facts = ready ? talkTimeFacts(balance, perMinute, recent.data.items) : null;
  const low = balance !== null && balance < LOW_BALANCE_MICROS;

  return (
    <section aria-labelledby="talk-time" className="relative overflow-hidden rounded-feature border border-line bg-surface shadow-2">
      <div className="relative grid items-center gap-6 px-5 py-6 sm:px-8 md:grid-cols-[260px_minmax(0,1fr)] md:gap-10">
        <div className="relative mx-auto w-[240px] md:w-[260px]">
          <Arc fill={facts?.fill ?? 0} low={low} />
          <div className="absolute inset-x-0 bottom-1 flex flex-col items-center">
            <span className="text-[13px] text-fg-3">about</span>
            {facts ? (
              <Ticker
                value={facts.minutes}
                fromZero
                format={(n) => Math.round(n).toLocaleString()}
                className="font-mono text-[40px] font-medium leading-none tracking-[-0.02em] text-fg"
              />
            ) : (
              <Skeleton className="my-1 h-9 w-24" />
            )}
            <span className="mt-1 flex items-center gap-1.5">
              <span id="talk-time" className="text-[13px] font-medium text-fg-2">
                minutes of calls
              </span>
              <InfoTip label="How talk time is worked out">
                Your balance divided by the per-minute price of your current stack ({name("stt")}, {name("llm")}, {name("tts")} and the platform fee),
                in whole minutes. Calls that run past their token or character bundle cost more per minute, so they use it faster.
              </InfoTip>
            </span>
          </div>
        </div>

        <div className="flex min-w-0 flex-col gap-4">
          <div>
            <p className="flex items-center gap-1.5 text-[13px] text-fg-3">
              Balance
              <InfoTip label="About the balance">
                Prepaid credit, shown to a tenth of a cent because calls are billed per second. New calls stop at $0.000; a call already in progress
                can finish within a small grace amount.
              </InfoTip>
            </p>
            {loading || balance === null ? (
              <Skeleton className="mt-1.5 h-9 w-40" />
            ) : (
              <MoneyText
                value={balanceUsd!}
                places={3}
                animate
                className={cn("mt-0.5 block text-[34px] font-medium leading-tight tracking-[-0.02em]", low ? "text-warning-text" : "text-fg")}
              />
            )}
          </div>
          <ul className="flex flex-col gap-2.5 text-[14px] text-fg-2">
            <li className="flex items-start gap-2.5">
              <Layers className="mt-0.5 size-4 shrink-0 text-fg-3" aria-hidden />
              <span>
                On your current stack: {name("stt")}, {name("llm")} and {name("tts")}
                {perMinute !== null && (
                  <>
                    {" "}
                    at <span className="font-mono text-fg tnum">{formatUsd(perMinute, { places: 4 })}</span> a minute
                  </>
                )}
                .
              </span>
            </li>
            <li className="flex items-start gap-2.5">
              <CalendarClock className="mt-0.5 size-4 shrink-0 text-fg-3" aria-hidden />
              {!facts ? (
                <Skeleton className="mt-1 h-3.5 w-64" />
              ) : facts.runOut ? (
                <span>
                  Lasts until about <span className="font-medium text-fg">{dateFmt.format(facts.runOut)}</span> at your recent{" "}
                  <span className="font-mono text-fg tnum">{formatUsd(facts.perDayMicros, { places: 2 })}</span> a day{" "}
                  <InfoTip label="How the run-out date is projected">
                    Recent spend is your call and feature charges over the last {SPEND_WINDOW_DAYS} days, averaged per day. The date is when this
                    balance reaches zero at that pace; top-ups and busier days move it.
                  </InfoTip>
                </span>
              ) : (
                <span>No calls in the last {SPEND_WINDOW_DAYS} days, so there is no run-out date yet.</span>
              )}
            </li>
            {low && (
              <li className="flex items-start gap-2.5 text-warning-text">
                <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
                <span>
                  {balance! <= 0n ? "New calls are refused until you add funds." : "Balance is low. Add funds to keep calls running."}{" "}
                  <InfoTip label="When calls stop" className="text-warning-text hover:text-warning-text">
                    New calls stop when the balance reaches $0.000. This warning starts below $1.000, so there is time to add funds first.
                  </InfoTip>
                </span>
              </li>
            )}
          </ul>
        </div>
      </div>
    </section>
  );
}

/** Semicircle gauge in the heat ramp, drawn from 0 to the fill on first render and on change. */
function Arc({ fill, low }: { fill: number; low: boolean }) {
  const id = useId().replace(/:/g, "");
  const reduce = useReducedMotion();
  const d = "M 20 130 A 110 110 0 0 1 240 130";
  return (
    <svg viewBox="0 0 260 140" className="block w-full" aria-hidden>
      <defs>
        <linearGradient id={`g-${id}`} x1="20" x2="240" y1="0" y2="0" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="var(--heat-1)" />
          <stop offset="0.55" stopColor="var(--heat-2)" />
          <stop offset="1" stopColor="var(--heat-3)" />
        </linearGradient>
      </defs>
      <path d={d} fill="none" stroke="var(--surface-3)" strokeWidth="14" strokeLinecap="round" />
      <motion.path
        d={d}
        fill="none"
        stroke={low ? "var(--warning)" : `url(#g-${id})`}
        strokeWidth="14"
        strokeLinecap="round"
        initial={{ pathLength: reduce ? fill : 0 }}
        animate={{ pathLength: Math.max(0.001, fill) }}
        transition={{ duration: reduce ? 0 : 0.9, ease: [0.16, 1, 0.3, 1] }}
      />
      {[0, 0.25, 0.5, 0.75, 1].map((p) => {
        const a = Math.PI * (1 - p);
        const x1 = 130 + Math.cos(a) * 92;
        const y1 = 130 - Math.sin(a) * 92;
        const x2 = 130 + Math.cos(a) * 86;
        const y2 = 130 - Math.sin(a) * 86;
        return <line key={p} x1={x1} y1={y1} x2={x2} y2={y2} stroke="var(--border-strong)" strokeWidth="1.5" strokeLinecap="round" />;
      })}
    </svg>
  );
}
