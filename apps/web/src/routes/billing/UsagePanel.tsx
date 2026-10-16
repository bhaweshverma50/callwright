import { CaretRight, ChartBar } from "@phosphor-icons/react";
import { Fragment, useState } from "react";
import { problemMessage } from "../../api/problems";
import { useUsage } from "../../api/queries";
import type { FeatureFamily } from "../../api/types";
import { EmptyState, Field, Input, MoneyText, Skeleton, cn, focusRing } from "../../components";

export const MAX_WINDOW_DAYS = 366;

export const FAMILY_LABELS: Record<FeatureFamily, string> = {
  calls: "Calls",
  evaluations: "Evaluations",
  simulations: "Simulations",
  analytics_chat: "Analytics questions",
  prompt_generation: "Prompt generation",
  post_call_analysis: "Post-call analysis",
};

const isoDay = (d: Date) => d.toISOString().slice(0, 10);
export function defaultWindow(now = new Date()) {
  const to = isoDay(now);
  const from = new Date(now);
  from.setUTCDate(from.getUTCDate() - 30);
  return { from: isoDay(from), to };
}

export function windowError(from: string, to: string): string | null {
  if (!from || !to) return "Pick both dates.";
  if (to < from) return "The end date must be on or after the start date.";
  const days = (Date.parse(to) - Date.parse(from)) / 86_400_000;
  if (days > MAX_WINDOW_DAYS) return `Pick a window of ${MAX_WINDOW_DAYS} days or less.`;
  return null;
}

const dayFmt = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
const pretty = (d: string) => dayFmt.format(new Date(`${d}T00:00:00Z`));

/** Usage per feature for a date window (T080, US4, FR-014): raw and billable cost, totals. */
export function UsagePanel() {
  const initial = defaultWindow();
  const [from, setFrom] = useState(initial.from);
  const [to, setTo] = useState(initial.to);
  const [open, setOpen] = useState<Set<FeatureFamily>>(new Set());
  const err = windowError(from, to);
  const q = useUsage(from, to, err === null);

  const toggle = (f: FeatureFamily) =>
    setOpen((s) => {
      const n = new Set(s);
      if (n.has(f)) n.delete(f);
      else n.add(f);
      return n;
    });

  return (
    <div className="rounded-panel border border-line bg-surface shadow-panel">
      <div className="flex flex-wrap items-end justify-between gap-4 border-b border-line px-4 py-3">
        <h2 className="text-[13.5px] font-semibold text-fg">Usage by feature</h2>
        <fieldset className="flex flex-wrap items-start gap-3">
          <legend className="sr-only">Date window</legend>
          <Field label="From" className="w-[150px]">
            {({ id, describedBy }) => (
              <Input id={id} type="date" inputSize="sm" className="font-mono tnum" value={from} max={to} onChange={(e) => setFrom(e.target.value)} aria-describedby={describedBy} aria-invalid={Boolean(err)} />
            )}
          </Field>
          <Field label="To" className="w-[150px]" error={err}>
            {({ id, describedBy }) => (
              <Input id={id} type="date" inputSize="sm" className="font-mono tnum" value={to} min={from} onChange={(e) => setTo(e.target.value)} aria-describedby={describedBy} aria-invalid={Boolean(err)} />
            )}
          </Field>
        </fieldset>
      </div>

      {err ? null : q.isPending ? (
        <div className="flex flex-col gap-3 p-4" aria-busy="true">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-4 w-full" />
          ))}
        </div>
      ) : q.isError ? (
        <EmptyState compact icon={<ChartBar />} title="Usage did not load">
          {problemMessage(q.error)}
        </EmptyState>
      ) : q.data.rows.length === 0 ? (
        <EmptyState compact icon={<ChartBar />} title="No usage charges yet in this window">
          Nothing was billed between {pretty(q.data.window.from)} and {pretty(q.data.window.to)}.
        </EmptyState>
      ) : (
        <table className={cn("w-full text-[13px] transition-opacity", q.isPlaceholderData && "opacity-60")}>
          <caption className="sr-only">
            Usage from {pretty(q.data.window.from)} to {pretty(q.data.window.to)}
          </caption>
          <thead>
            <tr className="border-b border-line font-mono text-[10.5px] uppercase tracking-[0.08em] text-fg-3">
              <th scope="col" className="h-8 pl-4 text-left font-medium">
                Feature
              </th>
              <th scope="col" className="px-3 text-right font-medium">
                Events
              </th>
              <th scope="col" className="px-3 text-right font-medium">
                Raw cost
              </th>
              <th scope="col" className="pl-3 pr-4 text-right font-medium">
                Billed
              </th>
            </tr>
          </thead>
          <tbody>
            {q.data.rows.map((r) => {
              const expanded = open.has(r.feature);
              return (
                <Fragment key={r.feature}>
                  <tr className="border-b border-line">
                    <th scope="row" className="h-10 pl-2 text-left font-normal">
                      <button
                        type="button"
                        aria-expanded={expanded}
                        onClick={() => toggle(r.feature)}
                        className={cn("inline-flex items-center gap-1.5 rounded-[5px] px-2 py-1 text-fg hover:bg-surface-2", focusRing)}
                      >
                        <CaretRight className={cn("size-3 text-fg-3 transition-transform", expanded && "rotate-90")} aria-hidden />
                        {FAMILY_LABELS[r.feature]}
                      </button>
                    </th>
                    <td className="px-3 text-right font-mono text-[12.5px] text-fg-2 tnum">{r.event_count.toLocaleString()}</td>
                    <td className="px-3 text-right text-[12.5px] text-fg-2">
                      <MoneyText value={r.raw_cost_usd} places={3} />
                    </td>
                    <td className="pl-3 pr-4 text-right text-[12.5px]">
                      <MoneyText value={r.billable_cost_usd} places={3} />
                    </td>
                  </tr>
                  {expanded &&
                    r.details.map((d) => (
                      <tr key={d.feature_key} className="border-b border-line bg-surface-2/60 text-[12px]">
                        <th scope="row" className="h-8 pl-11 text-left font-mono font-normal text-fg-2">
                          {d.feature_key}
                        </th>
                        <td className="px-3 text-right font-mono text-fg-3 tnum">{d.event_count.toLocaleString()}</td>
                        <td className="px-3 text-right text-fg-3">
                          <MoneyText value={d.raw_cost_usd} places={4} />
                        </td>
                        <td className="pl-3 pr-4 text-right text-fg-2">
                          <MoneyText value={d.billable_cost_usd} places={4} />
                        </td>
                      </tr>
                    ))}
                </Fragment>
              );
            })}
          </tbody>
          <tfoot>
            <tr className="bg-surface-2/60">
              <th scope="row" className="h-10 pl-4 text-left font-medium text-fg">
                Total
              </th>
              <td className="px-3 text-right font-mono text-[12.5px] text-fg-2 tnum">
                {q.data.rows.reduce((s, r) => s + r.event_count, 0).toLocaleString()}
              </td>
              <td className="px-3 text-right text-[12.5px] text-fg-2">
                <MoneyText value={q.data.total_raw_cost_usd} places={3} />
              </td>
              <td className="pl-3 pr-4 text-right text-[13px] font-medium">
                <MoneyText value={q.data.total_billable_cost_usd} places={3} />
              </td>
            </tr>
          </tfoot>
        </table>
      )}
    </div>
  );
}
