import { Timer } from "@phosphor-icons/react";
import { motion } from "motion/react";
import type { LatencySummary, TurnLatency } from "../../api/calls";
import { EmptyState, InfoTip, Skeleton, cn } from "../../components";
import { latencyTone } from "./format";
import { ms } from "../../lib/format";

const PARTS = [
  { key: "stt_final_ms", label: "Speech to text", color: "var(--heat-1)" },
  { key: "llm_ttft_ms", label: "Model first token", color: "var(--heat-2)" },
  { key: "tts_ttfb_ms", label: "Voice first audio", color: "var(--heat-3)" },
] as const;

const TONE_TEXT = { success: "text-success-text", warning: "text-warning-text", danger: "text-danger-text", neutral: "text-fg", accent: "text-fg" };

function Stat({ label, value, hint }: { label: string; value: number | null | undefined; hint?: string }) {
  return (
    <div className="flex flex-col gap-1 rounded-control border border-line bg-surface-2/50 px-3 py-2.5">
      <span className="flex items-center gap-1 text-[12px] text-fg-3">
        {label}
        {hint && <InfoTip label={`About ${label.toLowerCase()}`}>{hint}</InfoTip>}
      </span>
      <span className={cn("font-mono text-[16px] font-medium tnum", TONE_TEXT[latencyTone(value)])}>{ms(value)}</span>
    </div>
  );
}

/**
 * Measured latency (FR-012): the call's average, median and p95 end-to-end time, then every agent
 * turn as a bar split into its parts. Missing parts read "n/a"; nothing is estimated.
 */
export function LatencyPanel({ summary, turns, loading }: { summary: LatencySummary; turns: TurnLatency[] | undefined; loading?: boolean }) {
  const max = Math.max(1, ...(turns ?? []).map((t) => t.e2e_ms ?? 0));
  return (
    <div className="flex flex-col gap-5">
      <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
        <Stat label="Average" value={summary.avg_ms} hint="Mean time from the caller stopping to the agent's first audio, over measured turns." />
        <Stat label="Median" value={summary.p50_ms} />
        <Stat label="p95" value={summary.p95_ms} hint="95 percent of turns were answered at least this fast." />
        <div className="flex flex-col gap-1 rounded-control border border-line bg-surface-2/50 px-3 py-2.5">
          <span className="text-[12px] text-fg-3">Turns measured</span>
          <span className="font-mono text-[16px] font-medium text-fg tnum">{summary.turns_measured}</span>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px] text-fg-3" aria-hidden>
        {PARTS.map((p) => (
          <span key={p.key} className="flex items-center gap-1.5">
            <span className="size-2 rounded-full" style={{ background: p.color }} />
            {p.label}
          </span>
        ))}
        <span className="flex items-center gap-1.5">
          <span className="size-2 rounded-full bg-surface-3 ring-1 ring-line-strong" />
          Not attributed to a part
        </span>
      </div>
      {loading && !turns ? (
        <div className="flex flex-col gap-3" aria-hidden>
          {Array.from({ length: 5 }, (_, i) => (
            <Skeleton key={i} className="h-5 w-full" />
          ))}
        </div>
      ) : !turns || turns.length === 0 ? (
        <EmptyState compact icon={<Timer weight="duotone" />} title="No turns measured">
          Latency is recorded for every agent turn once the call connects.
        </EmptyState>
      ) : (
        <table className="w-full text-[13px]">
          <caption className="sr-only">Latency per agent turn, in milliseconds</caption>
          <thead>
            <tr className="text-left text-[12px] text-fg-3">
              <th scope="col" className="w-14 pb-2 font-normal">
                Turn
              </th>
              <th scope="col" className="pb-2 font-normal">
                <span className="sr-only">Parts</span>
              </th>
              {PARTS.map((p) => (
                <th key={p.key} scope="col" className="hidden w-[76px] pb-2 text-right font-normal md:table-cell">
                  {p.label.split(" ")[0]}
                </th>
              ))}
              <th scope="col" className="w-[76px] pb-2 text-right font-normal">
                Total
              </th>
            </tr>
          </thead>
          <tbody>
            {turns.map((t, row) => {
              const sum = PARTS.reduce((a, p) => a + (t[p.key] ?? 0), 0);
              const width = ((t.e2e_ms ?? sum) / max) * 100;
              return (
                <tr key={t.turn_index} className="border-t border-line/60">
                  <th scope="row" className="py-2 text-left font-mono font-normal text-fg-2 tnum">
                    {t.turn_index === 0 ? "Greet" : t.turn_index}
                  </th>
                  <td className="py-2 pr-3">
                    <motion.div
                      className="flex h-2.5 origin-left overflow-hidden rounded-full bg-surface-3"
                      style={{ width: `${Math.max(4, width)}%` }}
                      initial={{ scaleX: 0 }}
                      animate={{ scaleX: 1 }}
                      transition={{ duration: 0.5, delay: Math.min(row, 12) * 0.03, ease: [0.16, 1, 0.3, 1] }}
                      aria-hidden
                    >
                      {sum > 0 &&
                        PARTS.map((p) =>
                          t[p.key] == null ? null : (
                            <span
                              key={p.key}
                              style={{ width: `${((t[p.key] as number) / Math.max(sum, t.e2e_ms ?? 0)) * 100}%`, background: p.color }}
                            />
                          ),
                        )}
                    </motion.div>
                  </td>
                  {PARTS.map((p) => (
                    <td
                      key={p.key}
                      className={cn("hidden py-2 text-right font-mono tnum md:table-cell", t[p.key] == null ? "text-fg-3" : "text-fg-2")}
                    >
                      {t[p.key] == null ? "n/a" : t[p.key]}
                    </td>
                  ))}
                  <td className={cn("py-2 text-right font-mono font-medium tnum", TONE_TEXT[latencyTone(t.e2e_ms)])}>{t.e2e_ms ?? "n/a"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
