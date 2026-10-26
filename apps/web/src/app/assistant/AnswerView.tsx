import { ChevronRight } from "lucide-react";
import { useState } from "react";
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
import { cn, focusRing } from "../../components";
import { mss, usd } from "../../routes/calls/format";

export type ChatAnswer = components["schemas"]["ChatAnswer"];
type Column = NonNullable<NonNullable<ChatAnswer["table"]>["columns"]>[number];

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

/** An answer: the text, an optional chart or table from the server's numbers, and how it was computed. */
export function AnswerView({ answer }: { answer: ChatAnswer }) {
  const [open, setOpen] = useState(false);
  const columns = answer.table?.columns ?? [];
  const rows = answer.table?.rows ?? [];
  return (
    <div className="flex flex-col gap-3">
      <p className="text-[13.5px] leading-relaxed text-fg">{answer.content}</p>
      {answer.chart && answer.chart.data.length > 1 && <AnswerChart chart={answer.chart} columns={columns} />}
      {rows.length > 0 && (
        <div className="max-h-[220px] overflow-auto rounded-control border border-line">
          <table className="w-full text-[12.5px]">
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
                <li key={i} className="flex flex-col gap-0.5">
                  <span>
                    <span className="text-fg-3">Metrics</span> {q.metrics.join(", ")}
                  </span>
                  {q.group_by?.length ? (
                    <span>
                      <span className="text-fg-3">Grouped by</span> {q.group_by.join(", ")}
                    </span>
                  ) : null}
                  <span>
                    <span className="text-fg-3">Period</span> {q.period.preset.replace(/_/g, " ")}
                    {q.period.n_days ? ` (${q.period.n_days} days)` : ""}
                    {q.period.start_date ? ` ${q.period.start_date} to ${q.period.end_date}` : ""}
                  </span>
                  {q.filters && Object.values(q.filters).some((v) => Array.isArray(v) && v.length) && (
                    <span>
                      <span className="text-fg-3">Filters</span>{" "}
                      {Object.entries(q.filters)
                        .filter(([, v]) => Array.isArray(v) && v.length)
                        .map(([k, v]) => `${k.replace(/_/g, " ")}: ${(v as string[]).join(", ")}`)
                        .join("; ")}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
