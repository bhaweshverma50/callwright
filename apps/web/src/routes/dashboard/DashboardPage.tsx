import * as RP from "@radix-ui/react-popover";
import { useQueryClient } from "@tanstack/react-query";
import { Bot, Check, ChevronDown, PhoneCall, RefreshCw, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router";
import {
  callKeys,
  useAgentHealth,
  useAgentOptions,
  useDashboardQuality,
  useDashboardStats,
  useHasCalls,
  type DashboardPeriod,
} from "../../api/calls";
import { problemMessage } from "../../api/problems";
import { Button, Input, PageHeader, PanelLoader, Segmented, cn, focusRing } from "../../components";
import { FormAlert } from "../public/FormAlert";
import { viewerTimeZone } from "../calls/filters";
import { CallsChart, DurationTrend, TalkTimeChart } from "./charts/ActivityCharts";
import { ChannelSplit, DisconnectReasons, Distribution, Leaderboard, SentimentSplit } from "./charts/Breakdowns";
import { chartVars } from "./charts/ChartFrame";
import { DashboardPlaceholder } from "./DashboardPlaceholder";
import { KpiTiles } from "./KpiTiles";
import { AgentHealthCard, QualityGrid } from "./QualitySection";

export const PERIODS: { value: DashboardPeriod; label: string; long: string }[] = [
  { value: "last_7_days", label: "7d", long: "Last 7 days" },
  { value: "last_30_days", label: "30d", long: "Last 30 days" },
  { value: "last_90_days", label: "90d", long: "Last 90 days" },
  { value: "all_time", label: "All time", long: "All time" },
  { value: "custom", label: "Custom", long: "Custom range" },
];
const DEFAULT_PERIOD: DashboardPeriod = "last_30_days";
const APPLY_DELAY_MS = 300;

export interface DashboardSelection {
  period: DashboardPeriod;
  start: string;
  end: string;
  agents: string[];
}

export function readSelection(p: URLSearchParams): DashboardSelection {
  const raw = p.get("period");
  const period = PERIODS.some((x) => x.value === raw) ? (raw as DashboardPeriod) : DEFAULT_PERIOD;
  return {
    period,
    start: p.get("start_date") ?? "",
    end: p.get("end_date") ?? "",
    agents: (p.get("agent_ids") ?? "").split(",").filter((a) => /^agt_[A-Za-z0-9]+$/.test(a)),
  };
}

/** A custom range applies only once both dates are valid and in order (FR-039). */
export function rangeError(s: DashboardSelection): string | null {
  if (s.period !== "custom") return null;
  if (!s.start || !s.end) return "Pick a start and an end date.";
  if (s.end < s.start) return "End date must be on or after start date.";
  return null;
}

function toParams(s: DashboardSelection): URLSearchParams {
  const p = new URLSearchParams();
  if (s.period !== DEFAULT_PERIOD) p.set("period", s.period);
  if (s.period === "custom") {
    if (s.start) p.set("start_date", s.start);
    if (s.end) p.set("end_date", s.end);
  }
  if (s.agents.length) p.set("agent_ids", s.agents.join(","));
  return p;
}

function AgentPicker({ value, onChange, agents }: { value: string[]; onChange: (v: string[]) => void; agents: { id: string; name: string }[] }) {
  const label =
    value.length === 0 ? "All agents" : value.length === 1 ? (agents.find((a) => a.id === value[0])?.name ?? "1 agent") : `${value.length} agents`;
  return (
    <RP.Root>
      <RP.Trigger asChild>
        <Button variant="secondary" icon={<Bot aria-hidden />} aria-label={`Agents: ${label}`}>
          <span className="max-w-[160px] truncate">{label}</span>
          <ChevronDown className="text-fg-3" aria-hidden />
        </Button>
      </RP.Trigger>
      <RP.Portal>
        <RP.Content
          align="end"
          sideOffset={6}
          collisionPadding={12}
          className="z-50 w-[260px] rounded-panel border border-line bg-surface p-1.5 shadow-pop data-[state=open]:animate-pop-in"
        >
          <button
            type="button"
            onClick={() => onChange([])}
            className={cn(
              "flex h-9 w-full cursor-pointer items-center gap-2.5 rounded-[6px] px-2 text-[13px] text-fg hover:bg-accent-soft/60",
              focusRing,
            )}
          >
            <span
              className={cn(
                "grid size-4 place-items-center rounded-full border",
                value.length === 0 ? "grad-action border-transparent text-white" : "border-line-strong",
              )}
            >
              {value.length === 0 && <Check className="size-3" strokeWidth={3} aria-hidden />}
            </span>
            All agents
          </button>
          <div className="my-1 h-px bg-line" />
          <div className="max-h-[280px] overflow-y-auto">
            {agents.map((a) => {
              const on = value.includes(a.id);
              return (
                <button
                  key={a.id}
                  type="button"
                  role="menuitemcheckbox"
                  aria-checked={on}
                  onClick={() => onChange(on ? value.filter((v) => v !== a.id) : [...value, a.id])}
                  className={cn(
                    "flex h-9 w-full cursor-pointer items-center gap-2.5 rounded-[6px] px-2 text-left text-[13px] text-fg hover:bg-accent-soft/60",
                    focusRing,
                  )}
                >
                  <span
                    className={cn(
                      "grid size-4 shrink-0 place-items-center rounded-[4px] border",
                      on ? "grad-action border-transparent text-white" : "border-line-strong",
                    )}
                  >
                    {on && <Check className="size-3" strokeWidth={3} aria-hidden />}
                  </span>
                  <span className="truncate">{a.name}</span>
                </button>
              );
            })}
            {agents.length === 0 && <p className="px-2 py-2 text-[12.5px] text-fg-3">No agents yet.</p>}
          </div>
        </RP.Content>
      </RP.Portal>
    </RP.Root>
  );
}

const timeFmt = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });

/**
 * Fleet dashboard (US3): period presets, a custom range and an agent filter that apply on change,
 * KPI tiles with sparklines, activity and breakdown charts, quality pass rates and agent health.
 * A workspace without any call keeps the setup sequence.
 */
export function DashboardPage() {
  const has = useHasCalls();
  if (has.data === false) return <DashboardPlaceholder />;
  if (has.isPending) return <PanelLoader label="Loading the dashboard" />;
  return <Dashboard />;
}

function Dashboard() {
  const [params, setParams] = useSearchParams();
  const applied = useMemo(() => readSelection(params), [params]);
  const [draft, setDraft] = useState(applied);
  const [synced, setSynced] = useState(params.toString());
  if (params.toString() !== synced) {
    setSynced(params.toString());
    setDraft(applied);
  }
  const error = rangeError(draft);

  // Changes apply on their own after a short pause; an incomplete custom range waits (FR-039).
  useEffect(() => {
    if (error) return;
    const next = toParams(draft);
    if (next.toString() === params.toString()) return;
    const t = window.setTimeout(() => setParams(next, { replace: true }), APPLY_DELAY_MS);
    return () => window.clearTimeout(t);
  }, [draft, error, params, setParams]);

  const tz = useMemo(viewerTimeZone, []);
  const query = useMemo(() => {
    const q = new URLSearchParams({ period: applied.period, tz });
    if (applied.period === "custom" && !rangeError(applied)) {
      q.set("start_date", applied.start);
      q.set("end_date", applied.end);
    }
    if (applied.agents.length) q.set("agent_ids", applied.agents.join(","));
    return q;
  }, [applied, tz]);
  const validQuery = !rangeError(applied);
  const stats = useDashboardStats(query);
  const quality = useDashboardQuality(query);
  const health = useAgentHealth(query);
  const agents = useAgentOptions();
  const qc = useQueryClient();
  const [refreshing, setRefreshing] = useState(false);

  const refresh = async () => {
    setRefreshing(true);
    await qc.invalidateQueries({ queryKey: callKeys.dashboard });
    setRefreshing(false);
  };

  const updated = Math.max(stats.dataUpdatedAt, quality.dataUpdatedAt, health.dataUpdatedAt);
  const isDefault = draft.period === DEFAULT_PERIOD && draft.agents.length === 0;
  const periodLabel = PERIODS.find((p) => p.value === applied.period)!.long;
  const agentName = (id: string) => agents.data?.find((a) => a.id === id)?.name ?? id;
  const s = stats.data;

  return (
    <div className={chartVars}>
      <PageHeader
        title="Dashboard"
        description="Calls, cost, latency and quality across your agents."
        actions={
          <>
            {updated > 0 && (
              <span className="text-[12.5px] text-fg-3" aria-live="polite">
                Updated <span className="font-mono tnum">{timeFmt.format(new Date(updated))}</span>
              </span>
            )}
            <Button
              variant="secondary"
              icon={<RefreshCw className={cn(refreshing && "animate-spin")} aria-hidden />}
              onClick={() => void refresh()}
              disabled={refreshing}
            >
              Refresh
            </Button>
            <Button asChild variant="primary" icon={<PhoneCall aria-hidden />}>
              <Link to="/calls">View calls</Link>
            </Button>
          </>
        }
      />

      <div className="mb-5 flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <Segmented
            aria-label="Period"
            value={draft.period}
            onValueChange={(v) => setDraft((d) => ({ ...d, period: v }))}
            options={PERIODS.map((p) => ({ value: p.value, label: p.label }))}
          />
          <AnimatePresence initial={false}>
            {draft.period === "custom" && (
              <motion.div
                initial={{ opacity: 0, x: -6 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: -6 }}
                className="flex flex-wrap items-center gap-2"
              >
                <Input
                  inputSize="md"
                  type="date"
                  aria-label="Start date"
                  className="w-[150px]"
                  value={draft.start}
                  onChange={(e) => setDraft((d) => ({ ...d, start: e.target.value }))}
                  aria-invalid={Boolean(error && draft.start && draft.end) || undefined}
                />
                <span className="text-[12.5px] text-fg-3">to</span>
                <Input
                  inputSize="md"
                  type="date"
                  aria-label="End date"
                  className="w-[150px]"
                  value={draft.end}
                  onChange={(e) => setDraft((d) => ({ ...d, end: e.target.value }))}
                  aria-invalid={Boolean(error && draft.start && draft.end) || undefined}
                />
              </motion.div>
            )}
          </AnimatePresence>
          <div className="ml-auto">
            <AgentPicker value={draft.agents} onChange={(agentsSel) => setDraft((d) => ({ ...d, agents: agentsSel }))} agents={agents.data ?? []} />
          </div>
        </div>
        {error && draft.start && draft.end && (
          <p role="alert" className="text-[12.5px] text-danger-text">
            {error}
          </p>
        )}
        {!isDefault && (
          <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Active selection">
            {draft.period !== DEFAULT_PERIOD && (
              <span className="inline-flex h-7 items-center gap-1 rounded-full border border-accent/30 bg-accent-soft pl-3 pr-1 text-[12.5px] text-accent-text">
                {draft.period === "custom" && draft.start && draft.end
                  ? `${draft.start} to ${draft.end}`
                  : PERIODS.find((p) => p.value === draft.period)!.long}
                <button
                  type="button"
                  aria-label="Reset period"
                  onClick={() => setDraft((d) => ({ ...d, period: DEFAULT_PERIOD }))}
                  className={cn("grid size-5 cursor-pointer place-items-center rounded-full hover:bg-accent/15", focusRing)}
                >
                  <X className="size-3" aria-hidden />
                </button>
              </span>
            )}
            {draft.agents.map((a) => (
              <span
                key={a}
                className="inline-flex h-7 max-w-[220px] items-center gap-1 rounded-full border border-accent/30 bg-accent-soft pl-3 pr-1 text-[12.5px] text-accent-text"
              >
                <span className="truncate">{agentName(a)}</span>
                <button
                  type="button"
                  aria-label={`Remove ${agentName(a)}`}
                  onClick={() => setDraft((d) => ({ ...d, agents: d.agents.filter((x) => x !== a) }))}
                  className={cn("grid size-5 shrink-0 cursor-pointer place-items-center rounded-full hover:bg-accent/15", focusRing)}
                >
                  <X className="size-3" aria-hidden />
                </button>
              </span>
            ))}
            <Button
              variant="link"
              size="sm"
              className="ml-1 text-[12.5px]"
              onClick={() => setDraft({ period: DEFAULT_PERIOD, start: "", end: "", agents: [] })}
            >
              Clear all
            </Button>
          </div>
        )}
      </div>

      {stats.isError && validQuery && <FormAlert tone="error">{problemMessage(stats.error, "dashboard")}</FormAlert>}

      <div className={cn("flex flex-col gap-5 transition-opacity duration-200", stats.isPlaceholderData && "opacity-70")}>
        <section aria-label={`Key figures, ${periodLabel.toLowerCase()}`}>
          <KpiTiles stats={s} />
        </section>
        {s && (
          <>
            <div className="grid grid-cols-[minmax(0,1fr)] gap-5 lg:grid-cols-2">
              <CallsChart series={s.series} bucket={s.bucket} />
              <TalkTimeChart series={s.series} bucket={s.bucket} />
            </div>
            <div className="grid grid-cols-[minmax(0,1fr)] gap-5 lg:grid-cols-3">
              <DisconnectReasons data={s.disconnect_reasons} />
              <SentimentSplit data={s.sentiment} />
              <ChannelSplit data={s.channels} />
            </div>
            <div className="grid grid-cols-[minmax(0,1fr)] gap-5 lg:grid-cols-3">
              <DurationTrend series={s.series} />
              <Leaderboard rows={s.leaderboard} />
              <Distribution rows={s.distribution} />
            </div>
          </>
        )}
        <div className="grid grid-cols-[minmax(0,1fr)] gap-5 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
          <QualityGrid data={quality.data} />
          <AgentHealthCard data={health.data} />
        </div>
      </div>
    </div>
  );
}
