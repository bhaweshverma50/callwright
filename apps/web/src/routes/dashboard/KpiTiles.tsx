import { Clock, Gauge, PhoneCall, Timer, Wallet, type LucideIcon } from "lucide-react";
import { motion } from "motion/react";
import { useId, type ReactNode } from "react";
import type { DashboardStats } from "../../api/calls";
import { Skeleton, Ticker, cn } from "../../components";
import { mss, talkTime, usd } from "../calls/format";

/** A small area sparkline drawn as one SVG path; the latest point gets a dot.
 * The SVG stretches (preserveAspectRatio="none"), so the dot is an HTML element (an SVG circle
 * would turn into an oval) and the draw-in is a clip, not pathLength (with a non-scaling stroke
 * the dash is measured in screen pixels and the line stops short). */
export function Sparkline({ values, className }: { values: number[]; className?: string }) {
  const id = useId().replace(/:/g, "");
  if (values.length < 2) return <div className={cn("h-9", className)} />;
  const w = 120;
  const h = 36;
  const max = Math.max(...values, 0);
  const min = Math.min(...values, 0);
  const span = max - min || 1;
  const pts = values.map((v, i) => [(i / (values.length - 1)) * w, h - 3 - ((v - min) / span) * (h - 6)] as const);
  const line = pts.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const area = `${line} L${w},${h} L0,${h} Z`;
  const last = pts[pts.length - 1]!;
  return (
    <div className={cn("relative h-9 w-full", className)} aria-hidden>
      <motion.svg
        viewBox={`0 0 ${w} ${h}`}
        preserveAspectRatio="none"
        className="size-full overflow-visible"
        initial={{ clipPath: "inset(-4px 100% -4px 0)" }}
        animate={{ clipPath: "inset(-4px 0% -4px 0)" }}
        transition={{ duration: 0.9, ease: [0.16, 1, 0.3, 1] }}
      >
        <defs>
          <linearGradient id={`fill-${id}`} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0" stopColor="var(--heat-1)" stopOpacity="0.28" />
            <stop offset="1" stopColor="var(--heat-1)" stopOpacity="0" />
          </linearGradient>
          <linearGradient id={`line-${id}`} x1="0" x2={w} y1="0" y2="0" gradientUnits="userSpaceOnUse">
            <stop offset="0" stopColor="var(--heat-1)" />
            <stop offset="0.7" stopColor="var(--heat-2)" />
            <stop offset="1" stopColor="var(--heat-3)" />
          </linearGradient>
        </defs>
        <path d={area} fill={`url(#fill-${id})`} />
        <path
          d={line}
          fill="none"
          stroke={`url(#line-${id})`}
          strokeWidth="2"
          vectorEffect="non-scaling-stroke"
          strokeLinejoin="round"
          strokeLinecap="round"
        />
      </motion.svg>
      <motion.span
        className="absolute size-[7px] -translate-x-1/2 -translate-y-1/2 rounded-full border-[1.5px] border-surface bg-[var(--heat-3)]"
        style={{ left: `${(last[0] / w) * 100}%`, top: `${(last[1] / h) * 100}%` }}
        initial={{ opacity: 0, scale: 0 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ delay: 0.75, duration: 0.25 }}
      />
    </div>
  );
}

/** Median and p95 turn latency on a 0 to 2.5 s track with the 1 s and 1.6 s comfort marks. */
function LatencyTrack({ median, p95 }: { median: number | null | undefined; p95: number | null | undefined }) {
  const MAX = 2500;
  const at = (v: number) => `${Math.min(100, (v / MAX) * 100)}%`;
  if (median == null) return <div className="h-9" />;
  return (
    <div className="relative -mb-1 mt-auto h-9" aria-hidden>
      <div className="absolute inset-x-0 top-[15px] h-1.5 overflow-hidden rounded-full bg-surface-3">
        <div className="h-full w-[40%] bg-success/35" />
      </div>
      <div className="absolute top-[15px] h-1.5 w-[24%] bg-warning/35" style={{ left: "40%" }} />
      {p95 != null && (
        <motion.span
          className="absolute top-[11px] h-3.5 rounded-full bg-[linear-gradient(90deg,var(--heat-1),var(--heat-2))] opacity-80"
          style={{ left: at(median), width: `calc(${at(p95)} - ${at(median)})` }}
          initial={{ scaleX: 0 }}
          animate={{ scaleX: 1 }}
          transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1] }}
        />
      )}
      <span
        className="absolute top-[8px] size-5 -translate-x-1/2 rounded-full border-2 border-surface bg-[var(--heat-1)] shadow-1"
        style={{ left: at(median) }}
      />
      <span className="absolute bottom-0 left-0 font-mono text-[10px] text-fg-3">0</span>
      <span className="absolute bottom-0 right-0 font-mono text-[10px] text-fg-3">2.5s</span>
    </div>
  );
}

function Tile({
  icon: Icon,
  label,
  value,
  sub,
  spark,
  visual,
}: {
  icon: LucideIcon;
  label: string;
  value: ReactNode;
  sub: ReactNode;
  spark: number[];
  visual?: ReactNode;
}) {
  return (
    <div className="lift group relative flex min-w-0 flex-col gap-2 overflow-hidden rounded-panel border border-line bg-surface p-4 shadow-1">
      <span className="flex items-center gap-2 text-[13px] text-fg-3">
        <span className="grid size-7 place-items-center rounded-control bg-accent-soft text-accent-text transition-transform duration-200 [&_svg]:size-[15px]">
          <Icon aria-hidden />
        </span>
        {label}
      </span>
      <span className="truncate font-mono text-[19px] font-semibold sm:text-[22px] leading-none tracking-[-0.01em] text-fg tnum">{value}</span>
      <span className="min-h-[18px] text-[12px] text-fg-3">{sub}</span>
      {visual ?? <Sparkline values={spark} className="-mb-1 mt-auto" />}
    </div>
  );
}

const fmtDay = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short", timeZone: "UTC" });

/** KPI tiles (FR-018), each with its sparkline over the period's buckets. */
export function KpiTiles({ stats }: { stats: DashboardStats | undefined }) {
  if (!stats) {
    return (
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-5 [&>*:last-child]:col-span-2 xl:[&>*:last-child]:col-span-1" aria-hidden>
        {Array.from({ length: 5 }, (_, i) => (
          <div key={i} className="flex flex-col gap-3 rounded-panel border border-line bg-surface p-4 shadow-1">
            <Skeleton className="h-4 w-24" />
            <Skeleton className="h-6 w-20" />
            <Skeleton className="h-3 w-28" />
            <Skeleton className="h-9 w-full" />
          </div>
        ))}
      </div>
    );
  }
  const k = stats.kpis;
  const s = stats.sparklines;
  return (
    <div className="grid grid-cols-2 gap-3 xl:grid-cols-5 [&>*:last-child]:col-span-2 xl:[&>*:last-child]:col-span-1">
      <Tile
        icon={PhoneCall}
        label="Total calls"
        value={<Ticker value={k.total_calls} format={(n) => Math.round(n).toLocaleString()} />}
        sub={
          <>
            <span className="font-mono text-fg-2 tnum">{k.daily_avg_calls.toFixed(2)}</span> a day on average
          </>
        }
        spark={s.calls ?? []}
      />
      <Tile
        icon={Clock}
        label="Talk time"
        value={talkTime(k.total_duration_s)}
        sub={
          k.peak_day ? (
            <>
              Peak <span className="font-mono text-fg-2 tnum">{k.peak_day.total_calls}</span> calls on{" "}
              {fmtDay.format(new Date(`${k.peak_day.date}T00:00:00Z`))}
            </>
          ) : (
            "No busy day yet"
          )
        }
        spark={s.duration_s ?? []}
      />
      <Tile
        icon={Wallet}
        label="Total cost"
        value={<Ticker value={k.total_cost_usd} format={(n) => usd(n, 2)} />}
        sub={
          <>
            <span className="font-mono text-fg-2 tnum">{usd(k.cost_per_call_usd, 3)}</span> a call
          </>
        }
        spark={s.cost_usd ?? []}
      />
      <Tile icon={Timer} label="Average duration" value={mss(k.avg_duration_s)} sub="Connected calls" spark={s.avg_duration_s ?? []} />
      <Tile
        icon={Gauge}
        label="Median turn latency"
        value={k.median_turn_latency_ms != null ? `${k.median_turn_latency_ms} ms` : "n/a"}
        sub={
          k.p95_turn_latency_ms != null ? (
            <>
              p95 <span className="font-mono text-fg-2 tnum">{k.p95_turn_latency_ms} ms</span>
            </>
          ) : (
            "No turns measured"
          )
        }
        spark={[]}
        visual={<LatencyTrack median={k.median_turn_latency_ms} p95={k.p95_turn_latency_ms} />}
      />
    </div>
  );
}
