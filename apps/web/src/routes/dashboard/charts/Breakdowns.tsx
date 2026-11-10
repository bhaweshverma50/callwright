import { CircleHelp, Frown, Meh, Smile, ThumbsDown, ThumbsUp } from "lucide-react";
import { motion } from "motion/react";
import { Link } from "react-router";
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import type { Channel, DashboardStats, DisconnectReason, Sentiment } from "../../../api/calls";
import { CHANNEL_LABELS, cn, focusRing, REASON_LABELS, SENTIMENT_LABELS } from "../../../components";
import { ChartCard, ChartTooltip } from "./ChartFrame";
import { callsPath } from "../../../lib/paths";

const pct = (n: number, total: number) => (total ? `${Math.round((n / total) * 100)}%` : "0%");

/** A labelled horizontal bar (single hue, so value is magnitude, not identity). */
function BarRow({
  label,
  value,
  total,
  max,
  href,
  muted,
  index,
}: {
  label: string;
  value: number;
  total: number;
  max: number;
  href?: string;
  muted?: boolean;
  index: number;
}) {
  const inner = (
    <>
      <span className="flex items-baseline justify-between gap-3 text-[13px]">
        <span className="min-w-0 truncate text-fg">{label}</span>
        <span className="shrink-0 font-mono text-fg-2 tnum">
          {value.toLocaleString()} <span className="text-fg-3">{pct(value, total)}</span>
        </span>
      </span>
      <span className="mt-1.5 block h-2 overflow-hidden rounded-full bg-surface-3">
        <motion.span
          className={cn("block h-full origin-left rounded-full", muted ? "bg-line-strong" : "bg-[var(--series)]")}
          style={{ width: `${max ? Math.max(2, (value / max) * 100) : 0}%` }}
          initial={{ scaleX: 0 }}
          animate={{ scaleX: 1 }}
          transition={{ duration: 0.6, delay: index * 0.04, ease: [0.16, 1, 0.3, 1] }}
        />
      </span>
    </>
  );
  return href ? (
    <li>
      <Link to={href} className={cn("block rounded-control px-2 py-1.5 transition-colors hover:bg-accent-soft/40", focusRing)}>
        {inner}
      </Link>
    </li>
  ) : (
    <li className="px-2 py-1.5">{inner}</li>
  );
}

function Empty({ children }: { children: string }) {
  return <p className="py-8 text-center text-[13px] text-fg-3">{children}</p>;
}

/** Why calls ended; each bar opens the call list filtered to that reason. */
export function DisconnectReasons({ data }: { data: DashboardStats["disconnect_reasons"] }) {
  const rows = Object.entries(data)
    .map(([k, v]) => [k as DisconnectReason, v] as const)
    .sort((a, b) => b[1] - a[1]);
  const total = rows.reduce((a, [, v]) => a + v, 0);
  const max = rows[0]?.[1] ?? 0;
  return (
    <ChartCard title="Why calls ended" description="Open a reason to see its calls">
      {rows.length === 0 ? (
        <Empty>No ended calls in this period.</Empty>
      ) : (
        <ol className="-mx-2 flex flex-col">
          {rows.map(([k, v], i) => (
            <BarRow key={k} index={i} label={REASON_LABELS[k] ?? k} value={v} total={total} max={max} href={callsPath({ disconnect_reason: k })} />
          ))}
        </ol>
      )}
    </ChartCard>
  );
}

const SENTIMENT_STYLE: Record<Sentiment, { color: string; icon: typeof Smile }> = {
  positive: { color: "var(--success)", icon: Smile },
  neutral: { color: "var(--text-3)", icon: Meh },
  negative: { color: "var(--danger)", icon: Frown },
  unknown: { color: "var(--border-strong)", icon: CircleHelp },
};

/** Sentiment split as one 100% bar with status colours, an icon and a label per part. */
export function SentimentSplit({ data }: { data: DashboardStats["sentiment"] }) {
  const order: Sentiment[] = ["positive", "neutral", "negative", "unknown"];
  const total = order.reduce((a, k) => a + data[k], 0);
  return (
    <ChartCard title="Sentiment" description="How callers sounded, from post-call analysis">
      {total === 0 ? (
        <Empty>No analysed calls in this period.</Empty>
      ) : (
        <>
          <div
            className="flex h-3 gap-[2px] overflow-hidden rounded-full"
            role="img"
            aria-label={order.map((k) => `${SENTIMENT_LABELS[k]} ${data[k]}`).join(", ")}
          >
            {order.map((k, i) =>
              data[k] ? (
                <motion.span
                  key={k}
                  className="h-full origin-left first:rounded-l-full last:rounded-r-full"
                  style={{ width: `${(data[k] / total) * 100}%`, background: SENTIMENT_STYLE[k].color }}
                  initial={{ scaleX: 0 }}
                  animate={{ scaleX: 1 }}
                  transition={{ duration: 0.5, delay: i * 0.06 }}
                />
              ) : null,
            )}
          </div>
          <ul className="mt-4 grid grid-cols-2 gap-2">
            {order.map((k) => {
              const Icon = SENTIMENT_STYLE[k].icon;
              return (
                <li key={k}>
                  <Link
                    to={callsPath({ sentiment: k })}
                    className={cn(
                      "flex items-center gap-2 rounded-control border border-line px-3 py-2 transition-colors hover:border-accent/40 hover:bg-accent-soft/30",
                      focusRing,
                    )}
                  >
                    <Icon className="size-4 shrink-0" style={{ color: SENTIMENT_STYLE[k].color }} aria-hidden />
                    <span className="text-[13px] text-fg">{SENTIMENT_LABELS[k]}</span>
                    <span className="ml-auto font-mono text-[13px] text-fg-2 tnum">{pct(data[k], total)}</span>
                  </Link>
                </li>
              );
            })}
          </ul>
        </>
      )}
    </ChartCard>
  );
}

const CHANNEL_ORDER: Channel[] = ["web", "sip_inbound", "sip_outbound", "whatsapp"];
const CHANNEL_COLORS: Record<Channel, string> = {
  web: "var(--ch-1)",
  sip_inbound: "var(--ch-2)",
  sip_outbound: "var(--ch-3)",
  whatsapp: "var(--ch-4)",
};

/** Channel split: a donut with a legend that names every slice (identity never colour alone). */
export function ChannelSplit({ data }: { data: DashboardStats["channels"] }) {
  const rows = CHANNEL_ORDER.map((k) => ({ key: k, label: CHANNEL_LABELS[k], value: data[k] }));
  const total = rows.reduce((a, r) => a + r.value, 0);
  return (
    <ChartCard title="Channels" description="Where calls came from">
      {total === 0 ? (
        <Empty>No calls in this period.</Empty>
      ) : (
        <div className="flex flex-wrap items-center gap-5">
          <div className="relative size-[132px] shrink-0">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={rows.filter((r) => r.value > 0)}
                  dataKey="value"
                  nameKey="label"
                  innerRadius={44}
                  outerRadius={64}
                  paddingAngle={2}
                  stroke="var(--surface)"
                  strokeWidth={2}
                  animationDuration={700}
                >
                  {rows
                    .filter((r) => r.value > 0)
                    .map((r) => (
                      <Cell key={r.key} fill={CHANNEL_COLORS[r.key]} />
                    ))}
                </Pie>
                <Tooltip
                  content={({ active, payload }) =>
                    active && payload?.[0] ? (
                      <ChartTooltip
                        title={String(payload[0].name)}
                        rows={[{ label: "Calls", value: `${Number(payload[0].value).toLocaleString()} (${pct(Number(payload[0].value), total)})` }]}
                      />
                    ) : null
                  }
                />
              </PieChart>
            </ResponsiveContainer>
            <span className="pointer-events-none absolute inset-0 grid place-items-center text-center">
              <span>
                <span className="block font-mono text-[17px] font-semibold text-fg tnum">{total.toLocaleString()}</span>
                <span className="block text-[11px] text-fg-3">calls</span>
              </span>
            </span>
          </div>
          <ul className="flex min-w-[150px] flex-1 flex-col gap-2">
            {rows.map((r) => {
              return (
                <li key={r.key} className="flex items-center gap-2 whitespace-nowrap text-[13px]">
                  <span className="size-2.5 shrink-0 rounded-full" style={{ background: CHANNEL_COLORS[r.key] }} aria-hidden />
                  <span className="text-fg">{r.label}</span>
                  <span className="ml-auto font-mono text-fg-2 tnum">{r.value.toLocaleString()}</span>
                  <span className="w-9 text-right font-mono text-fg-3 tnum">{pct(r.value, total)}</span>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </ChartCard>
  );
}

/** The five busiest agents with their positive and negative calls. */
export function Leaderboard({ rows }: { rows: DashboardStats["leaderboard"] }) {
  const max = rows[0]?.total_calls ?? 0;
  return (
    <ChartCard title="Most active agents" description="Top 5 by calls" bodyClassName="px-0 pb-2 pt-2">
      {rows.length === 0 ? (
        <Empty>No calls in this period.</Empty>
      ) : (
        <table className="w-full text-[13px]">
          <caption className="sr-only">Most active agents</caption>
          <thead>
            <tr className="text-left text-[12px] text-fg-3">
              <th scope="col" className="pb-2 pl-5 font-normal">
                Agent
              </th>
              <th scope="col" className="pb-2 text-right font-normal">
                Calls
              </th>
              <th scope="col" className="pb-2 text-right font-normal">
                <span className="sr-only">Positive</span>
                <ThumbsUp className="ml-auto size-3.5 text-success-text" aria-hidden />
              </th>
              <th scope="col" className="pb-2 pr-5 text-right font-normal">
                <span className="sr-only">Negative</span>
                <ThumbsDown className="ml-auto size-3.5 text-danger-text" aria-hidden />
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={r.agent_id} className="border-t border-line/70 transition-colors hover:bg-accent-soft/25">
                <td className="py-2.5 pl-5">
                  <Link to={callsPath({ agent_id: r.agent_id })} className={cn("flex min-w-0 items-center gap-2.5 rounded-inline", focusRing)}>
                    <span className="grid size-6 shrink-0 place-items-center rounded-full bg-surface-3 font-mono text-[11px] text-fg-2">{i + 1}</span>
                    <span className="min-w-0">
                      <span className="block truncate text-fg">{r.agent_name}</span>
                      <span className="mt-1 block h-1 w-24 overflow-hidden rounded-full bg-surface-3">
                        <span
                          className="block h-full rounded-full bg-[var(--series)]"
                          style={{ width: `${max ? (r.total_calls / max) * 100 : 0}%` }}
                        />
                      </span>
                    </span>
                  </Link>
                </td>
                <td className="py-2.5 text-right font-mono text-fg tnum">{r.total_calls.toLocaleString()}</td>
                <td className="py-2.5 text-right font-mono text-success-text tnum">{r.positive_calls}</td>
                <td className="py-2.5 pr-5 text-right font-mono text-danger-text tnum">{r.negative_calls}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </ChartCard>
  );
}

/** Share of calls across the top 10 agents, the rest as "Others". */
export function Distribution({ rows }: { rows: DashboardStats["distribution"] }) {
  const total = rows.reduce((a, r) => a + r.total_calls, 0);
  const max = Math.max(0, ...rows.map((r) => r.total_calls));
  return (
    <ChartCard title="Calls by agent" description="Top 10 agents, the rest grouped as Others">
      {rows.length === 0 ? (
        <Empty>No calls in this period.</Empty>
      ) : (
        <ol className="-mx-2 flex flex-col">
          {rows.map((r, i) => (
            <BarRow
              key={r.agent_id}
              index={i}
              label={r.agent_name}
              value={r.total_calls}
              total={total}
              max={max}
              muted={r.agent_id === "others"}
              href={r.agent_id === "others" ? undefined : callsPath({ agent_id: r.agent_id })}
            />
          ))}
        </ol>
      )}
    </ChartCard>
  );
}
