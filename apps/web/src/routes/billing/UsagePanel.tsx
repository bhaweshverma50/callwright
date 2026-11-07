import { ChartBar } from "@phosphor-icons/react";
import {
  BookOpen,
  Bot,
  ChevronRight,
  ClipboardCheck,
  FileSearch,
  FlaskConical,
  MessageSquareText,
  Mic,
  PenLine,
  PhoneCall,
  Receipt,
  TestTubeDiagonal,
  TriangleAlert,
  type LucideIcon,
  Workflow,
} from "lucide-react";
import { Fragment, useState } from "react";
import { problemMessage } from "../../api/problems";
import { useUsage } from "../../api/queries";
import type { FeatureFamily } from "../../api/types";
import { EmptyState, Field, InfoTip, Input, MoneyText, Skeleton, TruncatedText, cn, focusRing } from "../../components";
import { operationExtensions } from "../../lib/contract.gen";

/** Calendar days a usage window may cover, both ends included (usage.yaml). */
export const MAX_WINDOW_DAYS = operationExtensions["GET /usage"]["x-max-window-days"];

/** Every family in usage.yaml FeatureFamily (T090), named the way users see the feature. */
export const FAMILY_LABELS: Record<FeatureFamily, string> = {
  calls: "Calls",
  evaluations: "Evaluations",
  simulations: "Simulations",
  testing: "Test runs",
  analytics_chat: "Analytics questions",
  prompt_generation: "Prompt generation",
  post_call_analysis: "Post-call analysis",
  flow_assistant: "Flow assistant",
  voice_copilot: "Voice copilot",
  issues: "Issue detection and fixes",
  knowledge_ingestion: "Knowledge ingestion",
  embedding: "Embeddings",
};

/** What each family covers, for the info tip beside its row. */
export const FAMILY_HINTS: Record<FeatureFamily, string> = {
  calls: "Per-minute charges for calls: speech to text, model, voice, noise cancellation and the platform fee.",
  evaluations: "Evaluators grading calls, each with its reasons.",
  simulations: "Simulated callers and replayed calls run against an agent version.",
  testing: "Test runs that check an agent before it takes real calls.",
  analytics_chat: "Questions about your calls, asked in plain language.",
  prompt_generation: "Agent prompts drafted from a description.",
  post_call_analysis: "Fields and summaries pulled from a call after it ends.",
  flow_assistant: "The assistant that proposes edits to a conversation flow.",
  voice_copilot: "Spoken commands that move around the app, such as asking for yesterday's failed calls.",
  issues: "Grouping repeated failures into issues and drafting prompt fixes for them.",
  knowledge_ingestion: "Reading documents into an agent's knowledge base.",
  embedding: "Turning text into vectors so agents can search your documents.",
};

export const FAMILY_ICONS: Record<FeatureFamily, LucideIcon> = {
  calls: PhoneCall,
  evaluations: ClipboardCheck,
  simulations: FlaskConical,
  testing: TestTubeDiagonal,
  analytics_chat: MessageSquareText,
  prompt_generation: PenLine,
  post_call_analysis: FileSearch,
  flow_assistant: Workflow,
  voice_copilot: Mic,
  issues: TriangleAlert,
  knowledge_ingestion: BookOpen,
  embedding: Bot,
};

function FamilyIcon({ family }: { family: FeatureFamily }) {
  const Icon = FAMILY_ICONS[family] ?? Receipt;
  return <Icon className="size-4 text-fg-3" aria-hidden />;
}

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
  const days = (Date.parse(to) - Date.parse(from)) / 86_400_000 + 1;
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
    <div className="rounded-panel border border-line bg-surface shadow-1">
      <div className="flex flex-wrap items-end justify-between gap-4 border-b border-line px-5 py-3.5">
        <div className="flex flex-col gap-0.5">
          <h2 className="text-[14px] font-semibold text-fg">Usage by feature</h2>
          <p className="text-[13px] text-fg-3">Raw cost is what vendors charged; billed is what came off your balance.</p>
        </div>
        <fieldset className="flex flex-wrap items-start gap-3">
          <legend className="sr-only">Date range</legend>
          <Field label="From" className="w-[150px]">
            {({ id, describedBy }) => (
              <Input
                id={id}
                type="date"
                className="font-mono tnum"
                value={from}
                max={to}
                onChange={(e) => setFrom(e.target.value)}
                aria-describedby={describedBy}
                aria-invalid={Boolean(err)}
              />
            )}
          </Field>
          <Field label="To" className="w-[150px]" error={err}>
            {({ id, describedBy }) => (
              <Input
                id={id}
                type="date"
                className="font-mono tnum"
                value={to}
                min={from}
                onChange={(e) => setTo(e.target.value)}
                aria-describedby={describedBy}
                aria-invalid={Boolean(err)}
              />
            )}
          </Field>
        </fieldset>
      </div>

      {err ? null : q.isPending ? (
        <div className="flex flex-col gap-3 p-5" aria-busy="true">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-4 w-full" />
          ))}
        </div>
      ) : q.isError ? (
        <EmptyState compact icon={<ChartBar weight="duotone" />} title="Usage did not load">
          {problemMessage(q.error)}
        </EmptyState>
      ) : q.data.rows.length === 0 ? (
        <EmptyState compact icon={<ChartBar weight="duotone" />} title="No usage charges yet in this window">
          Nothing was billed between {pretty(q.data.window.from)} and {pretty(q.data.window.to)}.
        </EmptyState>
      ) : (
        <table className={cn("w-full text-[13px] transition-opacity", q.isPlaceholderData && "opacity-60")}>
          <caption className="sr-only">
            Usage from {pretty(q.data.window.from)} to {pretty(q.data.window.to)}
          </caption>
          <thead>
            <tr className="whitespace-nowrap border-b border-line bg-surface-2/70 text-[12px] text-fg-3">
              <th scope="col" className="h-9 w-full max-w-0 pl-5 text-left font-medium">
                Feature
              </th>
              <th scope="col" className="px-3 text-right font-medium">
                Events
              </th>
              <th scope="col" className="px-3 text-right font-medium">
                Raw cost
              </th>
              <th scope="col" className="pl-3 pr-5 text-right font-medium">
                Billed
              </th>
            </tr>
          </thead>
          <tbody>
            {q.data.rows.map((r) => {
              const expanded = open.has(r.feature);
              return (
                <Fragment key={r.feature}>
                  <tr className="border-b border-line transition-colors hover:bg-accent-soft/35">
                    <th scope="row" className="h-11 max-w-0 pl-3 text-left font-normal">
                      <span className="flex min-w-0 items-center gap-1">
                        <button
                          type="button"
                          aria-expanded={expanded}
                          onClick={() => toggle(r.feature)}
                          className={cn(
                            "inline-flex min-w-0 cursor-pointer items-center gap-1.5 rounded-[6px] px-2 py-1 text-fg hover:bg-surface-2",
                            focusRing,
                          )}
                        >
                          <ChevronRight
                            className={cn("size-3.5 shrink-0 text-fg-3 transition-transform duration-200", expanded && "rotate-90")}
                            aria-hidden
                          />
                          <span className="shrink-0">
                            <FamilyIcon family={r.feature} />
                          </span>
                          <TruncatedText focusable={false}>{FAMILY_LABELS[r.feature] ?? r.feature}</TruncatedText>
                        </button>
                        {FAMILY_HINTS[r.feature] && (
                          <InfoTip label={`About ${(FAMILY_LABELS[r.feature] ?? r.feature).toLowerCase()}`}>{FAMILY_HINTS[r.feature]}</InfoTip>
                        )}
                      </span>
                    </th>
                    <td className="px-3 text-right font-mono text-[13px] text-fg-2 tnum">{r.event_count.toLocaleString()}</td>
                    <td className="px-3 text-right text-[13px] text-fg-2">
                      <MoneyText value={r.raw_cost_usd} places={3} />
                    </td>
                    <td className="pl-3 pr-5 text-right text-[13px]">
                      <MoneyText value={r.billable_cost_usd} places={3} />
                    </td>
                  </tr>
                  {expanded &&
                    r.details.map((d) => (
                      <tr key={d.feature_key} className="border-b border-line bg-surface-2/60 text-[12px]">
                        <th scope="row" className="h-9 max-w-0 pl-12 text-left font-mono font-normal text-fg-2">
                          <TruncatedText>{d.feature_key}</TruncatedText>
                        </th>
                        <td className="px-3 text-right font-mono text-fg-3 tnum">{d.event_count.toLocaleString()}</td>
                        <td className="px-3 text-right text-fg-3">
                          <MoneyText value={d.raw_cost_usd} places={4} />
                        </td>
                        <td className="pl-3 pr-5 text-right text-fg-2">
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
              <th scope="row" className="h-11 pl-5 text-left font-medium text-fg">
                Total
              </th>
              <td className="px-3 text-right font-mono text-[13px] text-fg-2 tnum">
                {q.data.rows.reduce((s, r) => s + r.event_count, 0).toLocaleString()}
              </td>
              <td className="px-3 text-right text-[13px] text-fg-2">
                <MoneyText value={q.data.total_raw_cost_usd} places={3} />
              </td>
              <td className="pl-3 pr-5 text-right text-[13px] font-medium">
                <MoneyText value={q.data.total_billable_cost_usd} places={3} />
              </td>
            </tr>
          </tfoot>
        </table>
      )}
    </div>
  );
}
