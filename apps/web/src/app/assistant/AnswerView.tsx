import { ArrowUpRight, ChevronRight, Clock3, CornerDownRight, Gauge, Lightbulb, PhoneCall, Wallet } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link } from "react-router";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { components } from "../../api/schema";
import { Badge, cn, focusRing, type Tone } from "../../components";
import { mss, STATUS_TONES, usd, when } from "../../routes/calls/format";

export type ChatAnswer = components["schemas"]["ChatAnswer"];
type Column = NonNullable<NonNullable<ChatAnswer["table"]>["columns"]>[number];
type Computed = ChatAnswer["computed_with"][number];
type CallQuery = components["schemas"]["CallQuery"];
type CallRow = {
  call_id: string;
  started_at?: string;
  agent_name?: string;
  origin?: string;
  status?: string;
  duration_s?: number | null;
  cost_usd?: number | null;
  avg_latency_ms?: number | null;
};

// Validated categorical slots (same set as the dashboard channel split); a fifth series folds into a table.
const SERIES = ["var(--ch-1)", "var(--ch-2)", "var(--ch-3)", "var(--ch-4)"];
const tick = { fill: "var(--text-3)", fontSize: 10.5 };
const dateFmt = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short", timeZone: "UTC" });

/** Axis labels stay short: whole dollars and seconds, thousands as k. */
function axisLabel(v: number, type: Column["type"] | undefined): string {
  if (type === "usd") return `$${v >= 100 ? Math.round(v) : Number(v.toFixed(2))}`;
  if (type === "seconds") return mss(v);
  if (type === "ratio") return `${Math.round(v * 100)}%`;
  return Math.abs(v) >= 1000 ? `${Number((v / 1000).toFixed(1))}k` : String(Number(v.toFixed(2)));
}

export function formatCell(value: unknown, type: Column["type"] | undefined): string {
  if (value === null || value === undefined) return "n/a";
  const n = Number(value);
  switch (type) {
    case "usd":
      return usd(n, 3);
    case "seconds":
      return mss(n);
    case "ms":
      return `${Math.round(n).toLocaleString()} ms`;
    case "ratio":
      return `${Math.round(n * 100)}%`;
    case "datetime":
      return when(String(value));
    case "call":
      return String(value);
    case "date":
      return /^\d{4}-\d{2}-\d{2}$/.test(String(value)) ? dateFmt.format(new Date(`${String(value)}T00:00:00Z`)) : String(value);
    case "integer":
      return Math.round(n).toLocaleString();
    case "number":
      return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
    default:
      return String(value);
  }
}

function AnswerChart({ chart, columns }: { chart: NonNullable<ChatAnswer["chart"]>; columns: Column[] }) {
  const typeOf = (key: string) => columns.find((c) => c.key === key)?.type;
  const series = (chart.series ?? []).slice(0, 4);
  const common = { data: chart.data, margin: { top: 6, right: 12, bottom: 0, left: 0 } };
  const tooltip = (
    <Tooltip
      contentStyle={{ background: "var(--tooltip-bg)", border: "none", borderRadius: 8, color: "var(--tooltip-fg)", fontSize: 12 }}
      labelStyle={{ color: "var(--tooltip-fg)" }}
      labelFormatter={(l) => formatCell(l, typeOf(chart.x_key ?? ""))}
      formatter={(v, name) => [formatCell(v, typeOf(String(name))), series.find((s) => s.key === name)?.label ?? String(name)]}
    />
  );
  const axes = (
    <>
      <CartesianGrid vertical={false} stroke="var(--border)" strokeDasharray="2 4" />
      <XAxis
        dataKey={chart.x_key}
        tick={tick}
        tickLine={false}
        axisLine={false}
        minTickGap={16}
        tickFormatter={(v: string) => formatCell(v, typeOf(chart.x_key ?? ""))}
      />
      <YAxis width={44} tick={tick} tickLine={false} axisLine={false} tickFormatter={(v: number) => axisLabel(v, typeOf(series[0]?.key ?? ""))} />
    </>
  );
  return (
    <div className="h-[200px] w-full" role="img" aria-label={`${chart.chart_type} chart of ${series.map((s) => s.label).join(" and ")}`}>
      <ResponsiveContainer width="100%" height="100%">
        {chart.chart_type === "pie" ? (
          <PieChart>
            <Pie
              data={chart.data}
              dataKey={series[0]?.key ?? "value"}
              nameKey={chart.x_key}
              innerRadius={48}
              outerRadius={78}
              paddingAngle={2}
              stroke="var(--surface)"
            >
              {chart.data.map((_, i) => (
                <Cell key={i} fill={i < 4 ? SERIES[i] : "var(--border-strong)"} />
              ))}
            </Pie>
            {tooltip}
          </PieChart>
        ) : chart.chart_type === "line" ? (
          <LineChart {...common}>
            {axes}
            {tooltip}
            {series.map((s, i) => (
              <Line key={s.key} type="monotoneX" dataKey={s.key ?? ""} stroke={SERIES[i]} strokeWidth={2} dot={false} />
            ))}
          </LineChart>
        ) : chart.chart_type === "area" ? (
          <AreaChart {...common}>
            {axes}
            {tooltip}
            {series.map((s, i) => (
              <Area key={s.key} type="monotoneX" dataKey={s.key ?? ""} stroke={SERIES[i]} fill={SERIES[i]} fillOpacity={0.15} strokeWidth={2} />
            ))}
          </AreaChart>
        ) : (
          <BarChart {...common} barCategoryGap="24%">
            {axes}
            {tooltip}
            {series.map((s, i) => (
              <Bar key={s.key} dataKey={s.key ?? ""} fill={SERIES[i]} radius={[4, 4, 0, 0]} maxBarSize={32} />
            ))}
          </BarChart>
        )}
      </ResponsiveContainer>
    </div>
  );
}

const ORIGIN_BADGE: Record<string, { label: string; tone: Tone } | undefined> = {
  test: { label: "Test call", tone: "accent" },
  simulation: { label: "Simulated", tone: "neutral" },
};

export const callHref = (id: string) => `/calls?call=${encodeURIComponent(id)}`;

function Stat({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5 rounded-control bg-surface-2/70 px-2.5 py-2">
      <span className="flex items-center gap-1 text-[11px] font-medium text-fg-3 [&_svg]:size-3">
        {icon}
        {label}
      </span>
      <span className="truncate font-mono text-[13px] text-fg tnum">{value}</span>
    </div>
  );
}

function CallBadges({ row }: { row: CallRow }) {
  const origin = row.origin ? ORIGIN_BADGE[row.origin] : undefined;
  const status = row.status as keyof typeof STATUS_TONES | undefined;
  return (
    <>
      {origin && <Badge tone={origin.tone}>{origin.label}</Badge>}
      {status && <Badge tone={STATUS_TONES[status] ?? "neutral"}>{status.replace(/_/g, " ")}</Badge>}
    </>
  );
}

/** Calls from a lookup: one featured card with its numbers, or a compact list; each opens the call. */
function CallResults({ rows, onNavigate }: { rows: CallRow[]; onNavigate?: () => void }) {
  if (rows.length === 1) {
    const r = rows[0]!;
    return (
      <Link
        to={callHref(r.call_id)}
        onClick={onNavigate}
        aria-label={`Open the call with ${r.agent_name ?? "the agent"}${r.started_at ? `, ${when(r.started_at)}` : ""}`}
        className={cn(
          "group flex flex-col gap-3 rounded-panel border border-line bg-surface p-3 transition-[border-color,box-shadow,transform] duration-200 hover:border-accent/45 hover:shadow-pop",
          focusRing,
        )}
      >
        <div className="flex items-start gap-2.5">
          <span className="bg-accent grid size-8 shrink-0 place-items-center rounded-control text-white">
            <PhoneCall className="size-3.5" aria-hidden />
          </span>
          <div className="flex min-w-0 flex-1 flex-col gap-1">
            <span className="truncate text-[14px] font-medium text-fg">{r.agent_name ?? "Agent"}</span>
            <span className="flex flex-wrap items-center gap-1.5 text-[12px] text-fg-3">
              {r.started_at && <span>{when(r.started_at)}</span>}
              <CallBadges row={r} />
            </span>
          </div>
          <ArrowUpRight
            className="size-4 shrink-0 text-fg-3 transition-transform duration-200 group-hover:translate-x-0.5 group-hover:text-accent-text"
            aria-hidden
          />
        </div>
        <div className="grid grid-cols-3 gap-1.5">
          <Stat icon={<Wallet aria-hidden />} label="Cost" value={r.cost_usd == null ? "Pricing" : usd(r.cost_usd, 3)} />
          <Stat icon={<Clock3 aria-hidden />} label="Duration" value={mss(Number(r.duration_s ?? 0))} />
          <Stat
            icon={<Gauge aria-hidden />}
            label="Latency"
            value={r.avg_latency_ms == null ? "n/a" : `${Math.round(r.avg_latency_ms).toLocaleString()} ms`}
          />
        </div>
        <span className="flex items-center gap-1 text-[13px] font-medium text-accent-text">
          Open call
          <ChevronRight className="size-3.5 transition-transform duration-200 group-hover:translate-x-0.5" aria-hidden />
        </span>
      </Link>
    );
  }
  return (
    <ul className="flex flex-col overflow-hidden rounded-panel border border-line">
      {rows.map((r) => (
        <li key={r.call_id} className="border-t border-line first:border-t-0">
          <Link
            to={callHref(r.call_id)}
            onClick={onNavigate}
            className={cn("group flex items-center gap-2.5 px-3 py-2.5 transition-colors duration-150 hover:bg-surface-2/80", focusRing)}
          >
            <span className="grid size-7 shrink-0 place-items-center rounded-full bg-accent-soft text-accent-text">
              <PhoneCall className="size-3.5" aria-hidden />
            </span>
            <span className="flex min-w-0 flex-1 flex-col gap-0.5">
              <span className="flex min-w-0 items-center gap-1.5">
                <span className="truncate text-[13px] font-medium text-fg">{r.agent_name ?? "Agent"}</span>
                {r.origin && ORIGIN_BADGE[r.origin] && <Badge tone={ORIGIN_BADGE[r.origin]!.tone}>{ORIGIN_BADGE[r.origin]!.label}</Badge>}
              </span>
              <span className="truncate text-[12px] text-fg-3">
                {[r.started_at ? when(r.started_at) : null, mss(Number(r.duration_s ?? 0)), r.status?.replace(/_/g, " ")].filter(Boolean).join(" · ")}
              </span>
            </span>
            <span className="font-mono text-[13px] text-fg-2 tnum">{r.cost_usd == null ? "n/a" : usd(r.cost_usd, 3)}</span>
            <ChevronRight
              className="size-3.5 shrink-0 text-fg-3 transition-transform duration-150 group-hover:translate-x-0.5 group-hover:text-fg"
              aria-hidden
            />
          </Link>
        </li>
      ))}
    </ul>
  );
}

export function SuggestionChips({ items, onAsk, label }: { items: string[]; onAsk?: (q: string) => void; label: string }) {
  if (!items.length || !onAsk) return null;
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-[12px] font-medium text-fg-3">{label}</span>
      <div className="flex flex-wrap gap-1.5">
        {items.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => onAsk(s)}
            className={cn(
              "group flex cursor-pointer items-center gap-1.5 rounded-full border border-line-strong bg-surface px-3 py-1.5 text-left text-[13px] text-fg-2 transition-[color,background-color,border-color,transform] duration-150 hover:border-accent/50 hover:bg-accent-soft/40 hover:text-fg active:translate-y-0",
              focusRing,
            )}
          >
            <CornerDownRight className="size-3 text-fg-3 transition-colors group-hover:text-accent-text" aria-hidden />
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}

const isCallQuery = (q: Computed): q is CallQuery => "kind" in q && q.kind === "calls";
const ORDER_LABEL: Record<string, string> = { recent: "newest first", cost: "by cost", duration: "by duration", latency: "by latency" };

function ComputedItem({ q }: { q: Computed }) {
  const included = (q.origins ?? (isCallQuery(q) ? ["live", "test"] : ["live"])).join(", ");
  const period = q.period ? (
    <>
      {q.period.preset.replace(/_/g, " ")}
      {q.period.n_days ? ` (${q.period.n_days} days)` : ""}
      {q.period.start_date ? ` ${q.period.start_date} to ${q.period.end_date}` : ""}
    </>
  ) : (
    "any time"
  );
  const filters = q.filters && Object.entries(q.filters).filter(([, v]) => Array.isArray(v) && v.length);
  return (
    <li className="flex flex-col gap-0.5">
      {isCallQuery(q) ? (
        <span>
          <span className="text-fg-3">Calls</span>{" "}
          {q.call_id ? q.call_id : `${ORDER_LABEL[q.order ?? "recent"]}${q.direction === "asc" ? " (ascending)" : ""}, up to ${q.limit ?? 5}`}
        </span>
      ) : (
        <>
          <span>
            <span className="text-fg-3">Metrics</span> {q.metrics.join(", ")}
          </span>
          {q.group_by?.length ? (
            <span>
              <span className="text-fg-3">Grouped by</span> {q.group_by.join(", ")}
            </span>
          ) : null}
        </>
      )}
      <span>
        <span className="text-fg-3">Period</span> {period}
      </span>
      <span>
        <span className="text-fg-3">Includes</span> {included} calls
      </span>
      {filters && filters.length > 0 && (
        <span>
          <span className="text-fg-3">Filters</span> {filters.map(([k, v]) => `${k.replace(/_/g, " ")}: ${(v as string[]).join(", ")}`).join("; ")}
        </span>
      )}
    </li>
  );
}

/** A declined question: what the assistant can do instead and examples to tap, never a dead end. */
function Declined({ answer, onAsk }: { answer: ChatAnswer; onAsk?: (q: string) => void }) {
  return (
    <div className="flex flex-col gap-3 rounded-panel border border-line bg-surface-2/60 p-3">
      <div className="flex items-start gap-2.5">
        <span className="grid size-7 shrink-0 place-items-center rounded-control bg-accent-soft text-accent-text">
          <Lightbulb className="size-3.5" aria-hidden />
        </span>
        <p className="text-[14px] leading-relaxed text-fg">{answer.content}</p>
      </div>
      <SuggestionChips items={answer.suggestions ?? []} onAsk={onAsk} label="Try asking" />
    </div>
  );
}

/** An answer: the text, an optional chart, table or call cards from the server's numbers, and how it was computed. */
export function AnswerView({ answer, onAsk, onNavigate }: { answer: ChatAnswer; onAsk?: (q: string) => void; onNavigate?: () => void }) {
  const [open, setOpen] = useState(false);
  if (answer.outcome === "declined") return <Declined answer={answer} onAsk={onAsk} />;
  const columns = answer.table?.columns ?? [];
  const rows = answer.table?.rows ?? [];
  const callRows = columns.some((c) => c.type === "call") ? (rows as CallRow[]) : null;
  // One row of plain numbers (no grouping) reads better as figures than as a one-cell table.
  const scalar = rows.length === 1 && columns.length <= 4 && columns.every((c) => c.type !== "string" && c.type !== "date");
  return (
    <div className="flex flex-col gap-3">
      <p className="text-[14px] leading-relaxed text-fg">{answer.content}</p>
      {callRows && callRows.length > 0 && <CallResults rows={callRows} onNavigate={onNavigate} />}
      {!callRows && answer.chart && answer.chart.data.length > 1 && <AnswerChart chart={answer.chart} columns={columns} />}
      {!callRows && scalar && (
        <div className={cn("grid gap-1.5", columns.length > 1 ? "grid-cols-2" : "grid-cols-1 sm:grid-cols-2")}>
          {columns.map((c) => (
            <div key={c.key} className="flex flex-col gap-0.5 rounded-control border border-line bg-surface-2/60 px-3 py-2">
              <span className="text-[11px] font-medium text-fg-3">{c.label}</span>
              <span className="font-display text-[20px] tracking-[-0.01em] text-fg tnum">
                {formatCell((rows[0] as Record<string, unknown>)[c.key ?? ""], c.type)}
              </span>
            </div>
          ))}
        </div>
      )}
      {!callRows && !scalar && rows.length > 0 && (
        <div className="max-h-[220px] overflow-auto rounded-control border border-line">
          <table className="w-full text-[13px]">
            <caption className="sr-only">Answer data</caption>
            <thead className="sticky top-0 bg-surface-2">
              <tr>
                {columns.map((c) => (
                  <th
                    key={c.key}
                    scope="col"
                    className={cn("px-2.5 py-1.5 font-medium text-fg-3", c.type === "string" || c.type === "date" ? "text-left" : "text-right")}
                  >
                    {c.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i} className="border-t border-line">
                  {columns.map((c) => (
                    <td
                      key={c.key}
                      className={cn(
                        "px-2.5 py-1.5",
                        c.type === "string" || c.type === "date" ? "text-left text-fg" : "text-right font-mono text-fg-2 tnum",
                      )}
                    >
                      {formatCell((r as Record<string, unknown>)[c.key ?? ""], c.type)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {answer.truncated && <p className="text-[12px] text-fg-3">Showing the first 100 rows.</p>}
      <SuggestionChips items={answer.suggestions ?? []} onAsk={onAsk} label="Follow up" />
      {answer.computed_with.length > 0 && (
        <div>
          <button
            type="button"
            aria-expanded={open}
            onClick={() => setOpen((o) => !o)}
            className={cn("flex cursor-pointer items-center gap-1 rounded-inline text-[12px] text-fg-3 hover:text-fg", focusRing)}
          >
            <ChevronRight className={cn("size-3.5 transition-transform duration-200", open && "rotate-90")} aria-hidden />
            How this was computed
          </button>
          {open && (
            <ul className="mt-2 flex flex-col gap-1.5 rounded-control bg-surface-2/70 px-3 py-2 text-[12px] text-fg-2">
              {answer.computed_with.map((q, i) => (
                <ComputedItem key={i} q={q} />
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
