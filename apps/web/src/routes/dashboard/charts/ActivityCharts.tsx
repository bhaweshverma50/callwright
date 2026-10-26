import { useId } from "react";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { DashboardStats } from "../../../api/calls";
import { mss, talkTime } from "../../calls/format";
import { ChartCard, ChartTooltip, axisTick, bucketLabel } from "./ChartFrame";

type Series = DashboardStats["series"];

const HEIGHT = 220;
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
      <div style={{ height: HEIGHT }} className="-ml-3">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={series} margin={{ top: 8, right: 22, bottom: 0, left: 0 }} barCategoryGap="22%">
            <defs>
              <linearGradient id={`bars-${id}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0" stopColor="var(--violet)" />
                <stop offset="1" stopColor="var(--series)" />
              </linearGradient>
            </defs>
            <CartesianGrid vertical={false} stroke="var(--border)" strokeDasharray="2 4" />
            <XAxis dataKey="bucket_start" tickFormatter={bucketLabel} minTickGap={24} {...tickProps} />
            <YAxis allowDecimals={false} width={36} {...tickProps} />
            <Tooltip
              cursor={{ fill: "var(--accent-soft)", opacity: 0.55, radius: 4 }}
              content={({ active, payload }) =>
                active && payload?.[0] ? (
                  <ChartTooltip
                    title={`${bucketWord(bucket)} ${bucketLabel(String(payload[0].payload.bucket_start))}`.trim()}
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
      <div style={{ height: HEIGHT }} className="-ml-3">
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
            <XAxis dataKey="bucket_start" tickFormatter={bucketLabel} minTickGap={24} {...tickProps} />
            <YAxis width={36} tickFormatter={(v: number) => `${v}m`} {...tickProps} />
            <Tooltip
              cursor={{ stroke: "var(--border-strong)", strokeDasharray: "3 3" }}
              content={({ active, payload }) =>
                active && payload?.[0] ? (
                  <ChartTooltip
                    title={`${bucketWord(bucket)} ${bucketLabel(String(payload[0].payload.bucket_start))}`.trim()}
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
      <div style={{ height: HEIGHT }} className="-ml-3">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 22, bottom: 0, left: 0 }}>
            <CartesianGrid vertical={false} stroke="var(--border)" strokeDasharray="2 4" />
            <XAxis dataKey="bucket_start" tickFormatter={bucketLabel} minTickGap={24} {...tickProps} />
            <YAxis width={40} tickFormatter={(v: number) => mss(v)} {...tickProps} />
            <Tooltip
              cursor={{ stroke: "var(--border-strong)", strokeDasharray: "3 3" }}
              content={({ active, payload }) =>
                active && payload?.[0] ? (
                  <ChartTooltip
                    title={bucketLabel(String(payload[0].payload.bucket_start))}
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
