import { useId } from "react";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { DashboardStats } from "../../../api/calls";
import { ChartCard, ChartTooltip } from "./ChartFrame";
import { dayLabel, mss, talkTime } from "../../../lib/format";
import { axisTick } from "../../../components";

type Series = DashboardStats["series"];

const HEIGHT = 220;

/** The chart's numbers as a table for screen readers (the chart itself is decorative to them). */
function SeriesTable({ caption, series, value }: { caption: string; series: Series; value: (s: Series[number]) => string }) {
  return (
    <table className="sr-only">
      <caption>{caption}</caption>
      <tbody>
        {series.map((s) => (
          <tr key={s.bucket_start}>
            <th scope="row">{dayLabel(s.bucket_start)}</th>
            <td>{value(s)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
const tickProps = { tickLine: false, axisLine: false, tick: axisTick } as const;

function bucketWord(bucket: DashboardStats["bucket"]) {
  return bucket === "week" ? "Week of" : "";
}

/** Calls per day (or week): one series, so no legend; the title names it. */
export function CallsChart({ series, bucket }: { series: Series; bucket: DashboardStats["bucket"] }) {
  const id = useId().replace(/:/g, "");
  const peak = Math.max(0, ...series.map((s) => s.total_calls));
  return (
    <ChartCard
      title={bucket === "week" ? "Calls per week" : "Calls per day"}
      description="Live calls that finished in the period"
      aside={
        <span className="text-right text-[12px] text-fg-3">
          Peak <span className="font-mono text-[13px] text-fg tnum">{peak.toLocaleString()}</span>
        </span>
      }
    >
      <SeriesTable caption="Calls per bucket" series={series} value={(s) => String(s.total_calls)} />
      <div style={{ height: HEIGHT }} className="-ml-3" aria-hidden>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={series} margin={{ top: 8, right: 22, bottom: 0, left: 0 }} barCategoryGap="22%">
            <defs>
              <linearGradient id={`bars-${id}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0" stopColor="var(--violet)" />
                <stop offset="1" stopColor="var(--series)" />
              </linearGradient>
            </defs>
            <CartesianGrid vertical={false} stroke="var(--border)" strokeDasharray="2 4" />
            <XAxis dataKey="bucket_start" tickFormatter={dayLabel} minTickGap={24} {...tickProps} />
            <YAxis allowDecimals={false} width={36} {...tickProps} />
            <Tooltip
              cursor={{ fill: "var(--accent-soft)", opacity: 0.55, radius: 4 }}
              content={({ active, payload }) =>
                active && payload?.[0] ? (
                  <ChartTooltip
                    title={`${bucketWord(bucket)} ${dayLabel(String(payload[0].payload.bucket_start))}`.trim()}
                    rows={[{ label: "Calls", value: Number(payload[0].value).toLocaleString() }]}
                  />
                ) : null
              }
            />
            <Bar dataKey="total_calls" fill={`url(#bars-${id})`} radius={[4, 4, 0, 0]} maxBarSize={28} animationDuration={700} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </ChartCard>
  );
}

/** Talk time per bucket, as an area so the eye reads volume. */
export function TalkTimeChart({ series, bucket }: { series: Series; bucket: DashboardStats["bucket"] }) {
  const id = useId().replace(/:/g, "");
  const data = series.map((s) => ({ ...s, minutes: Math.round((s.total_duration_s / 60) * 10) / 10 }));
  return (
    <ChartCard title={bucket === "week" ? "Talk time per week" : "Talk time per day"} description="Connected minutes, rounded up per call">
      <SeriesTable caption="Talk time per bucket" series={series} value={(s) => talkTime(s.total_duration_s)} />
      <div style={{ height: HEIGHT }} className="-ml-3" aria-hidden>
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 8, right: 22, bottom: 0, left: 0 }}>
            <defs>
              <linearGradient id={`area-${id}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0" stopColor="var(--heat-1)" stopOpacity={0.32} />
                <stop offset="1" stopColor="var(--heat-1)" stopOpacity={0.02} />
              </linearGradient>
              <linearGradient id={`stroke-${id}`} x1="0" y1="0" x2="1" y2="0">
                <stop offset="0" stopColor="var(--heat-1)" />
                <stop offset="1" stopColor="var(--heat-2)" />
              </linearGradient>
            </defs>
            <CartesianGrid vertical={false} stroke="var(--border)" strokeDasharray="2 4" />
            <XAxis dataKey="bucket_start" tickFormatter={dayLabel} minTickGap={24} {...tickProps} />
            <YAxis width={36} tickFormatter={(v: number) => `${v}m`} {...tickProps} />
            <Tooltip
              cursor={{ stroke: "var(--border-strong)", strokeDasharray: "3 3" }}
              content={({ active, payload }) =>
                active && payload?.[0] ? (
                  <ChartTooltip
                    title={`${bucketWord(bucket)} ${dayLabel(String(payload[0].payload.bucket_start))}`.trim()}
                    rows={[{ label: "Talk time", value: talkTime(Number(payload[0].payload.total_duration_s)) }]}
                  />
                ) : null
              }
            />
            <Area
              type="monotoneX"
              dataKey="minutes"
              stroke={`url(#stroke-${id})`}
              strokeWidth={2}
              fill={`url(#area-${id})`}
              activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--surface)", fill: "var(--heat-1)" }}
              animationDuration={800}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </ChartCard>
  );
}

/** Average connected call length per bucket; empty buckets break the line instead of reading 0. */
export function DurationTrend({ series }: { series: Series }) {
  const data = series.map((s) => ({ ...s, avg: s.total_calls ? s.avg_duration_s : null }));
  return (
    <ChartCard title="Average duration" description="Connected calls only">
      <SeriesTable caption="Average duration per bucket" series={series} value={(s) => (s.total_calls ? mss(s.avg_duration_s) : "No calls")} />
      <div style={{ height: HEIGHT }} className="-ml-3" aria-hidden>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 22, bottom: 0, left: 0 }}>
            <CartesianGrid vertical={false} stroke="var(--border)" strokeDasharray="2 4" />
            <XAxis dataKey="bucket_start" tickFormatter={dayLabel} minTickGap={24} {...tickProps} />
            <YAxis width={40} tickFormatter={(v: number) => mss(v)} {...tickProps} />
            <Tooltip
              cursor={{ stroke: "var(--border-strong)", strokeDasharray: "3 3" }}
              content={({ active, payload }) =>
                active && payload?.[0] ? (
                  <ChartTooltip
                    title={dayLabel(String(payload[0].payload.bucket_start))}
                    rows={[{ label: "Average", value: payload[0].value == null ? "No calls" : mss(Number(payload[0].value)) }]}
                  />
                ) : null
              }
            />
            <Line
              type="monotoneX"
              dataKey="avg"
              stroke="var(--series)"
              strokeWidth={2}
              dot={false}
              connectNulls={false}
              activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--surface)", fill: "var(--series)" }}
              animationDuration={800}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </ChartCard>
  );
}
