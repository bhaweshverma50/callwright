import { Heartbeat, ShieldCheck } from "@phosphor-icons/react";
import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";
import type { ReactNode } from "react";
import type { AgentHealth, DashboardQuality } from "../../api/calls";
import { Skeleton, cn } from "../../components";
import { ChartCard } from "./charts/ChartFrame";

const rate = (r: number | null | undefined) => (r == null ? "n/a" : `${Math.round(r * 100)}%`);

function Delta({ pp }: { pp: number | null | undefined }) {
  if (pp == null) return <span className="text-[12px] text-fg-3">No prior data</span>;
  const Icon = pp > 0 ? ArrowUpRight : pp < 0 ? ArrowDownRight : Minus;
  const tone = pp > 0 ? "text-success-text" : pp < 0 ? "text-danger-text" : "text-fg-3";
  return (
    <span className={cn("inline-flex items-center gap-0.5 font-mono text-[12px] tnum", tone)}>
      <Icon className="size-3.5" aria-hidden />
      {pp > 0 ? "+" : ""}
      {pp} pp
    </span>
  );
}

function EmptyQuality({ icon, title, children }: { icon: ReactNode; title: string; children: string }) {
  return (
    <div className="flex items-start gap-3 rounded-control border border-dashed border-line-strong bg-surface-2/40 px-4 py-4">
      <span className="grid size-9 shrink-0 place-items-center rounded-control bg-accent-soft text-accent-text [&_svg]:size-5">{icon}</span>
      <div>
        <p className="text-[13px] font-medium text-fg">{title}</p>
        <p className="mt-0.5 text-[13px] leading-relaxed text-fg-3">{children}</p>
      </div>
    </div>
  );
}

/** Per-evaluator pass rates for the period against the prior period (FR-020). */
export function QualityGrid({ data }: { data: DashboardQuality | undefined }) {
  const prior = new Map((data?.per_evaluator_prior ?? []).map((e) => [e.evaluator_id, e]));
  return (
    <ChartCard title="Quality checks" description="Pass rate per evaluator, against the previous period of the same length">
      {!data ? (
        <Skeleton className="h-20 w-full" />
      ) : data.per_evaluator.length === 0 ? (
        <EmptyQuality icon={<ShieldCheck weight="duotone" />} title="No evaluator runs in this period.">
          Turn on quality checks for an agent to see pass rates.
        </EmptyQuality>
      ) : (
        <ul className="grid grid-cols-[minmax(0,1fr)] gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {data.per_evaluator.map((e) => {
            const before = prior.get(e.evaluator_id)?.pass_rate;
            const pp = e.pass_rate != null && before != null ? Math.round((e.pass_rate - before) * 1000) / 10 : null;
            return (
              <li key={e.evaluator_id} className="flex flex-col gap-2 rounded-control border border-line px-3.5 py-3">
                <span className="truncate text-[13px] font-medium text-fg">{e.display_name}</span>
                <span className="flex items-baseline justify-between">
                  <span className="font-mono text-[20px] font-semibold text-fg tnum">{rate(e.pass_rate)}</span>
                  <Delta pp={pp} />
                </span>
                <span className="h-1.5 overflow-hidden rounded-full bg-surface-3">
                  <span className="block h-full rounded-full bg-success" style={{ width: `${(e.pass_rate ?? 0) * 100}%` }} />
                </span>
                <span className="font-mono text-[12px] text-fg-3 tnum">
                  {e.pass_count} pass, {e.fail_count} fail, {e.not_applicable_count} n/a
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </ChartCard>
  );
}

/** Headline evaluators over the last 30 days against the 30 before (FR-021). */
export function AgentHealthCard({ data }: { data: AgentHealth | undefined }) {
  return (
    <ChartCard title="Agent health" description="Last 30 days against the 30 days before">
      {!data ? (
        <Skeleton className="h-20 w-full" />
      ) : data.items.length === 0 ? (
        <EmptyQuality icon={<Heartbeat weight="duotone" />} title="No headline evaluators yet">
          Mark an evaluator as a headline check to follow its pass rate here.
        </EmptyQuality>
      ) : (
        <ul className="flex flex-col divide-y divide-line">
          {data.items.map((i) => (
            <li key={i.evaluator_id} className="flex items-center justify-between gap-3 py-2.5">
              <span className="truncate text-[13px] text-fg">{i.display_name}</span>
              <span className="flex items-center gap-3">
                <span className="font-mono text-[15px] font-semibold text-fg tnum">{rate(i.pass_rate)}</span>
                <Delta pp={i.delta_pp} />
              </span>
            </li>
          ))}
        </ul>
      )}
    </ChartCard>
  );
}
