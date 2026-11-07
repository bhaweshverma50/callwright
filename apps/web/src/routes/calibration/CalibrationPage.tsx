import { Crosshair } from "@phosphor-icons/react";
import { ArrowRight, Crosshair as CrosshairIcon, Info, Scale, SlidersHorizontal, Tags, UsersRound, type LucideIcon } from "lucide-react";
import { motion } from "motion/react";
import { useMemo, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router";
import { useAgentOptions } from "../../api/calls";
import { problemMessage } from "../../api/problems";
import { useCalibrationRows, useCalibrationSummary, type CalibrationRow, type VersionScope } from "../../api/quality";
import { Badge, Button, EmptyState, PageHeader, Segmented, Select, Skeleton, cn, type Tone } from "../../components";
import { COST_LABELS, evaluatorIcon } from "../agents/quality/evaluatorMeta";

const LOOKBACKS = [30, 90, 180, 365] as const;
const ALL_AGENTS = "all";
const pct = (r: number | null | undefined) => (r == null ? "n/a" : `${Math.round(r * 100)}%`);

export const READINGS: Record<CalibrationRow["reading"], { label: string; tone: Tone; body: string }> = {
  strong: { label: "Strong agreement", tone: "success", body: "Its verdicts match your labels on most calls. You can rely on it." },
  over_eager: { label: "Over-eager", tone: "warning", body: "It flags calls you consider fine. Loosen it so it fails fewer calls." },
  misses: { label: "Misses problems", tone: "warning", body: "It passes calls you marked bad. Tighten it so it catches more." },
  partial: { label: "Partial agreement", tone: "accent", body: "Some verdicts match your labels and some do not, with no clear lean either way." },
  low: { label: "Low agreement", tone: "danger", body: "It disagrees with your labels more often than not. Treat its verdicts with caution." },
  insufficient: { label: "Not enough data", tone: "neutral", body: "Label more calls this check has scored before trusting the figure." },
};

function Tile({ icon: Icon, label, value, hint }: { icon: LucideIcon; label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="relative flex flex-col gap-2 overflow-hidden rounded-panel border border-line bg-surface p-4 shadow-1">
      <span
        aria-hidden
        className="pointer-events-none absolute -right-10 -top-10 size-28 rounded-full bg-[radial-gradient(closest-side,var(--glow-a),transparent)]"
      />
      <span className="flex items-center gap-2 text-[13px] text-fg-3">
        <Icon className="size-4" aria-hidden />
        {label}
      </span>
      <span className="font-mono text-[26px] font-semibold leading-none text-fg tnum">{value}</span>
      {hint && <span className="text-[12px] text-fg-3">{hint}</span>}
    </div>
  );
}

function Cell({ label, sub, value, good, n }: { label: string; sub: string; value: number; good: boolean; n: number }) {
  const share = n ? value / n : 0;
  return (
    <div
      className={cn(
        "relative flex flex-col gap-0.5 overflow-hidden rounded-control border p-2.5",
        good ? "border-success/30 bg-success-soft/50" : "border-warning/30 bg-warning-soft/50",
      )}
    >
      <motion.span
        aria-hidden
        className={cn("absolute inset-x-0 bottom-0", good ? "bg-success/15" : "bg-warning/20")}
        initial={{ height: 0 }}
        animate={{ height: `${share * 100}%` }}
        transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1] }}
      />
      <span className="relative font-mono text-[20px] font-semibold leading-none text-fg tnum">{value}</span>
      <span className={cn("relative text-[12px] font-medium", good ? "text-success-text" : "text-warning-text")}>{label}</span>
      <span className="relative text-[11px] leading-snug text-fg-3">{sub}</span>
    </div>
  );
}

function AgreementRing({ rate, low, high }: { rate: number | null | undefined; low?: number; high?: number }) {
  const r = 26;
  const c = 2 * Math.PI * r;
  const value = rate ?? 0;
  return (
    <div className="relative grid size-[68px] shrink-0 place-items-center">
      <svg viewBox="0 0 64 64" className="absolute inset-0 size-full -rotate-90" aria-hidden>
        <defs>
          <linearGradient id="agree-grad" x1="0" x2="1" y1="0" y2="1">
            <stop offset="0" stopColor="var(--heat-1)" />
            <stop offset="1" stopColor="var(--accent)" />
          </linearGradient>
        </defs>
        <circle cx="32" cy="32" r={r} fill="none" stroke="var(--surface-3)" strokeWidth="6" />
        {low != null && high != null && (
          <circle
            cx="32"
            cy="32"
            r={r}
            fill="none"
            stroke="var(--accent-soft)"
            strokeWidth="6"
            strokeDasharray={`${(high - low) * c} ${c}`}
            strokeDashoffset={-low * c}
          />
        )}
        <motion.circle
          cx="32"
          cy="32"
          r={r}
          fill="none"
          stroke="url(#agree-grad)"
          strokeWidth="6"
          strokeLinecap="round"
          strokeDasharray={c}
          initial={{ strokeDashoffset: c }}
          animate={{ strokeDashoffset: c * (1 - value) }}
          transition={{ duration: 0.9, ease: [0.16, 1, 0.3, 1] }}
        />
      </svg>
      <span className="font-mono text-[15px] font-semibold text-fg tnum">{pct(rate)}</span>
    </div>
  );
}

function thresholdHint(row: CalibrationRow): string | null {
  if (row.under_min_sample || row.best_threshold == null || row.current_threshold == null) return null;
  if (row.best_threshold === row.current_threshold) return `The current threshold ${row.current_threshold} already agrees best with your labels.`;
  const dir = row.best_threshold > row.current_threshold ? "Raise" : "Lower";
  return `${dir} the threshold from ${row.current_threshold} to ${row.best_threshold}: agreement would be ${pct(row.best_threshold_agreement)} on the same calls.`;
}

function MatrixCard({ row, min, index }: { row: CalibrationRow; min: number; index: number }) {
  const Icon = evaluatorIcon(row.evaluator_name);
  const reading = READINGS[row.reading];
  const grey = row.under_min_sample;
  const hint = thresholdHint(row);
  return (
    <motion.li
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: Math.min(index, 10) * 0.04, duration: 0.3 }}
      className={cn("flex flex-col gap-4 rounded-panel border border-line bg-surface p-4 shadow-1", grey && "bg-surface-2/60 shadow-none")}
      aria-label={`${row.display_name}${row.flow_node_label ? `, ${row.flow_node_label}` : ""}`}
    >
      <div className="flex items-start gap-3">
        <span
          className={cn(
            "grid size-9 shrink-0 place-items-center rounded-control [&_svg]:size-[18px]",
            grey ? "bg-surface-3 text-fg-3" : "bg-accent text-white",
          )}
        >
          <Icon aria-hidden />
        </span>
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className={cn("text-[14px] font-semibold", grey ? "text-fg-2" : "text-fg")}>{row.display_name}</span>
            {row.flow_node_label && <Badge tone="accent">{row.flow_node_label}</Badge>}
            {row.evaluator_version != null && <span className="font-mono text-[11px] text-fg-3">v{row.evaluator_version}</span>}
          </span>
          <span className="text-[12px] text-fg-3">
            {COST_LABELS[row.cost_class]} · {row.n} labelled and evaluated {row.n === 1 ? "call" : "calls"}
          </span>
        </div>
      </div>
      {grey ? (
        <div className="flex items-start gap-2.5 rounded-control border border-dashed border-line-strong px-3 py-3 text-fg-3">
          <Info className="mt-0.5 size-4 shrink-0" aria-hidden />
          <div className="flex flex-col gap-0.5">
            <span className="text-[13px] font-medium text-fg-2">
              Not enough data ({row.n} of {min})
            </span>
            <span className="text-[13px]">
              Label {min - row.n} more scored {min - row.n === 1 ? "call" : "calls"} to see how far this check can be trusted.
            </span>
          </div>
        </div>
      ) : (
        <>
          <div className="flex items-center gap-4">
            <AgreementRing rate={row.agreement_rate} low={row.agreement_ci?.low} high={row.agreement_ci?.high} />
            <div className="flex min-w-0 flex-col gap-1">
              <Badge tone={reading.tone} className="w-fit">
                {reading.label}
              </Badge>
              <span className="text-[13px] leading-relaxed text-fg-2">{reading.body}</span>
              {row.agreement_ci?.low != null && row.agreement_ci.high != null && (
                <span className="font-mono text-[12px] text-fg-3 tnum">
                  95% range {pct(row.agreement_ci.low)} to {pct(row.agreement_ci.high)}
                </span>
              )}
            </div>
          </div>
          <div className="grid grid-cols-[auto_1fr_1fr] gap-1.5 text-[12px]" role="table" aria-label={`${row.display_name} agreement matrix`}>
            <span role="columnheader" />
            <span role="columnheader" className="px-1 text-fg-3">
              You said good
            </span>
            <span role="columnheader" className="px-1 text-fg-3">
              You said bad
            </span>
            <span role="rowheader" className="self-center pr-1 text-fg-3 [writing-mode:vertical-rl] rotate-180">
              Passed
            </span>
            <Cell label="Both pass" sub="Check and you agree" value={row.both_pass} good n={row.n} />
            <Cell label="Missed" sub="Check passed a bad call" value={row.missed} good={false} n={row.n} />
            <span role="rowheader" className="self-center pr-1 text-fg-3 [writing-mode:vertical-rl] rotate-180">
              Failed
            </span>
            <Cell label="Over-eager" sub="Check failed a good call" value={row.over_eager} good={false} n={row.n} />
            <Cell label="Both fail" sub="Check and you agree" value={row.both_fail} good n={row.n} />
          </div>
          {hint && (
            <p className="flex items-start gap-2 rounded-control bg-accent-soft/50 px-3 py-2 text-[13px] text-accent-text">
              <SlidersHorizontal className="mt-0.5 size-3.5 shrink-0" aria-hidden />
              {hint}
            </p>
          )}
        </>
      )}
    </motion.li>
  );
}

/**
 * Calibration (US4, T054): per check, how its verdicts line up with people's labels on the same
 * calls, with a 95% range and a plain reading. Checks under the minimum sample stay greyed.
 */
export function CalibrationPage() {
  const [params, setParams] = useSearchParams();
  const agent = params.get("agent") ?? ALL_AGENTS;
  const agentId = agent === ALL_AGENTS ? null : agent;
  const lookback = Number(params.get("days") ?? 90) || 90;
  const scope = (params.get("versions") === "all" ? "all" : "current") as VersionScope;
  const rows = useCalibrationRows(agentId, lookback, scope);
  const summary = useCalibrationSummary(agentId, lookback);
  const agents = useAgentOptions();
  const set = (k: string, v: string | null) => {
    const p = new URLSearchParams(params);
    if (v === null) p.delete(k);
    else p.set(k, v);
    setParams(p, { replace: true });
  };
  const min = rows.data?.min_sample_for_signal ?? summary.data?.min_sample_for_signal ?? 5;
  const items = rows.data?.items ?? [];
  const trusted = items.filter((r) => !r.under_min_sample);
  const agentOptions = useMemo(
    () => [{ value: ALL_AGENTS, label: "All agents" }, ...(agents.data ?? []).map((a) => ({ value: a.id, label: a.name }))],
    [agents.data],
  );
  const s = summary.data;
  return (
    <>
      <PageHeader
        title="Calibration"
        description="How often each check agrees with the labels people gave the same calls. Trust a check once it has enough labelled calls and agrees strongly."
        actions={
          <Button asChild variant="secondary" icon={<ArrowRight aria-hidden />}>
            <Link to="/review">Label calls</Link>
          </Button>
        }
      />
      <div className="mb-5 flex flex-wrap items-center gap-3">
        <Select
          aria-label="Agent"
          size="sm"
          className="w-52"
          value={agent}
          onValueChange={(v) => set("agent", v === ALL_AGENTS ? null : v)}
          options={agentOptions}
        />
        <Segmented
          aria-label="Lookback"
          size="sm"
          value={String(lookback)}
          onValueChange={(v) => set("days", v === "90" ? null : v)}
          options={LOOKBACKS.map((d) => ({ value: String(d), label: `${d} days` }))}
        />
        <Segmented
          aria-label="Versions"
          size="sm"
          value={scope}
          onValueChange={(v) => set("versions", v === "current" ? null : v)}
          options={[
            { value: "current", label: "Current version" },
            { value: "all", label: "All versions" },
          ]}
        />
      </div>
      <div className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Tile icon={Tags} label="Labelled calls" value={s ? s.annotated_calls : <Skeleton className="h-6 w-10" />} />
        <Tile
          icon={Scale}
          label="Labelled and evaluated"
          value={s ? s.annotated_and_evaluated_calls : <Skeleton className="h-6 w-10" />}
          hint="Count toward a check's matrix"
        />
        <Tile
          icon={UsersRound}
          label="Conflicting labels"
          value={s ? s.conflicting_label_calls : <Skeleton className="h-6 w-10" />}
          hint="Ties between people, left out"
        />
        <Tile icon={CrosshairIcon} label="Minimum sample" value={min} hint={`${trusted.length} of ${items.length} checks have enough data`} />
      </div>
      {rows.isPending ? (
        <ul className="grid grid-cols-[minmax(0,1fr)] gap-3 md:grid-cols-2 xl:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-[300px] rounded-panel" />
          ))}
        </ul>
      ) : rows.isError ? (
        <EmptyState icon={<Crosshair weight="duotone" />} title="Calibration could not load">
          {problemMessage(rows.error, "calibration")}
        </EmptyState>
      ) : items.length === 0 ? (
        <EmptyState
          icon={<Crosshair weight="duotone" />}
          title="No checks to calibrate yet"
          actions={
            <Button asChild variant="primary">
              <Link to="/review">Open the review queue</Link>
            </Button>
          }
        >
          A check shows here once some of the calls it scored have a good or bad label. Label calls from the review queue or the call list.
        </EmptyState>
      ) : (
        <ul className="grid grid-cols-[minmax(0,1fr)] gap-3 md:grid-cols-2 xl:grid-cols-3" aria-label="Checks">
          {items.map((r, i) => (
            <MatrixCard key={`${r.evaluator_id}-${r.flow_node_id ?? ""}`} row={r} min={min} index={i} />
          ))}
        </ul>
      )}
    </>
  );
}
