import * as RP from "@radix-ui/react-popover";
import { Server, Zap } from "lucide-react";
import { useRef, useState } from "react";
import { useCall, type CostView } from "../../api/calls";
import { COMPONENT_ICONS, COMPONENT_LABELS, CostBreakdownCard, Skeleton, cn, focusRing } from "../../components";
import { costViewToBreakdown, mss, usd } from "./format";

/** The full receipt in the call drawer: 001's receipt fed from the 006 cost view. */
export function CostPanel({ cost }: { cost: CostView }) {
  return <CostBreakdownCard breakdown={costViewToBreakdown(cost)} title="Cost breakdown" />;
}

/** Header figures of a cost view: duration, billed minutes and the average rate a minute. */
export function CostHeader({ cost, className }: { cost: CostView; className?: string }) {
  const h = cost.header;
  return (
    <dl className={cn("flex flex-wrap gap-x-3 gap-y-0.5 text-[12px] text-fg-3", className)}>
      <div className="flex gap-1">
        <dt className="sr-only">Duration</dt>
        <dd className="font-mono tnum">{mss(h.duration_s)}</dd>
      </div>
      <div className="flex gap-1">
        <dt className="sr-only">Billed minutes</dt>
        <dd className="font-mono tnum">{h.billed_minutes.toFixed(2)}m</dd>
      </div>
      <div className="flex gap-1">
        <dt className="sr-only">Average rate</dt>
        <dd>
          <span className="font-mono tnum">{usd(h.avg_rate_per_min_usd, 3)}/m</span> avg
        </dd>
      </div>
    </dl>
  );
}

function CompactReceipt({ cost }: { cost: CostView }) {
  return (
    <div className="flex flex-col gap-2.5">
      <div className="flex flex-col gap-0.5">
        <span className="text-[13px] font-semibold text-fg">Cost breakdown</span>
        <CostHeader cost={cost} />
      </div>
      <ul className="flex flex-col divide-y divide-line/70 border-y border-dashed border-line-strong">
        {cost.lines.map((l) => {
          const Icon = COMPONENT_ICONS[l.component] ?? Server;
          return (
            <li key={l.component} className="flex items-center gap-2 py-1.5 text-[12.5px]">
              <Icon className="size-3.5 text-fg-3" aria-hidden />
              <span className="text-fg">{COMPONENT_LABELS[l.component] ?? l.component}</span>
              <span className="ml-auto font-mono text-[12px] text-fg-3 tnum">{l.billed_minutes.toFixed(2)}m</span>
              <span className="w-[54px] text-right font-mono text-fg tnum">{usd(l.cost_usd)}</span>
            </li>
          );
        })}
      </ul>
      {cost.surcharges.length > 0 && (
        <ul className="flex flex-col gap-1 rounded-control bg-warning-soft/70 px-2.5 py-2">
          {cost.surcharges.map((s) => (
            <li key={s.component} className="flex items-center gap-2 text-[12px] text-warning-text">
              <Zap className="size-3.5 shrink-0" aria-hidden />
              <span>
                {s.label} <span className="font-mono tnum">{s.multiplier.toFixed(2)}x</span>
              </span>
              <span className="ml-auto font-mono tnum">+{usd(s.surcharge_usd, 4)}</span>
            </li>
          ))}
        </ul>
      )}
      <div className="flex items-baseline justify-between">
        <span className="text-[12.5px] text-fg-2">Total</span>
        <span className="font-mono text-[14px] font-semibold text-fg tnum">{usd(cost.header.total_usd)}</span>
      </div>
    </div>
  );
}

function PopoverBody({ callId }: { callId: string }) {
  const detail = useCall(callId);
  if (detail.data?.cost) return <CompactReceipt cost={detail.data.cost} />;
  if (detail.data && !detail.data.cost) return <p className="text-[12.5px] text-fg-3">This call has not been priced yet.</p>;
  return (
    <div className="flex flex-col gap-2" aria-hidden>
      <Skeleton className="h-3.5 w-32" />
      {Array.from({ length: 4 }, (_, i) => (
        <Skeleton key={i} className="h-3 w-full" />
      ))}
    </div>
  );
}

/**
 * Cost cell with the itemised breakdown on hover or keyboard focus (US1 scenario 3). The lines
 * load on first open, so the list itself stays one query.
 */
export function CostCell({ callId, value }: { callId: string; value: number | null | undefined }) {
  const [open, setOpen] = useState(false);
  const timer = useRef<number | undefined>(undefined);
  if (value === null || value === undefined) return <span className="text-fg-3">n/a</span>;
  const show = () => {
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setOpen(true), 220);
  };
  const hide = () => {
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setOpen(false), 120);
  };
  return (
    <RP.Root open={open} onOpenChange={setOpen}>
      <RP.Trigger asChild>
        <button
          type="button"
          onPointerEnter={show}
          onPointerLeave={hide}
          onClick={(e) => e.stopPropagation()}
          aria-label={`Cost ${usd(value)}, show breakdown`}
          className={cn(
            "cursor-pointer rounded-inline font-mono text-[12.5px] text-fg underline decoration-line-strong decoration-dotted underline-offset-4 tnum hover:decoration-accent",
            focusRing,
          )}
        >
          {usd(value)}
        </button>
      </RP.Trigger>
      <RP.Portal>
        <RP.Content
          side="left"
          align="center"
          sideOffset={8}
          onPointerEnter={show}
          onPointerLeave={hide}
          onOpenAutoFocus={(e) => e.preventDefault()}
          className="z-50 w-[320px] rounded-panel border border-line bg-surface p-3.5 shadow-pop data-[state=open]:animate-pop-in"
        >
          <PopoverBody callId={callId} />
        </RP.Content>
      </RP.Portal>
    </RP.Root>
  );
}
