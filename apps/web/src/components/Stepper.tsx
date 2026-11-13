import { Check } from "lucide-react";
import { motion } from "motion/react";
import type { ReactNode } from "react";
import { cn } from "./cn";
import { ActiveDisc } from "./FlowChain";

export type StepStatus = "done" | "active" | "pending";

export interface Step {
  title: string;
  description: ReactNode;
  status: StepStatus;
  icon?: ReactNode;
  /** Shown inside the active row (the step's primary action). */
  action?: ReactNode;
}

/**
 * Vertical stepper for a real sequence (numbered because order matters). Geometry: every row has
 * the same 16px padding and a 40px circle at its top left, so all circles share one centre axis
 * at 36px from the row edge. Each row draws two segments: top edge to its circle centre, and
 * circle centre to bottom edge; rows touch, so the line is continuous. The active row is a raised
 * card stacked above its neighbours and draws no segments, so the line meets its edges and runs
 * under its shadow instead of through it. Segments
 * after a done step fill with the accent, the rest are muted.
 */
export function Stepper({ steps, label = "Steps" }: { steps: Step[]; label?: string }) {
  return (
    <ol aria-label={label} className="@container flex flex-col">
      {steps.map((s, i) => {
        const last = i === steps.length - 1;
        const filled = s.status === "done";
        const active = s.status === "active";
        return (
          <li
            key={s.title}
            aria-current={active ? "step" : undefined}
            className={cn(
              "relative flex gap-4 rounded-panel p-4 transition-[background-color,box-shadow] duration-200",
              // Active row: a subtle full-row lift, stacked above its neighbours. No borders or side stripes.
              active && "z-[1] bg-surface shadow-[0_10px_28px_-16px_hsl(var(--shadow-color)/0.45)] dark:bg-surface-3/45",
            )}
          >
            {/* The active row is a raised card: it draws no connector, so the line stops at its edges and runs under its shadow. */}
            {i > 0 && !active && <Connector className="top-0 h-[36px]" filled={steps[i - 1]?.status === "done"} delay={0.1 * i + 0.1} />}
            {!last && !active && <Connector className="top-[36px] bottom-0" filled={filled} delay={0.1 * i} />}
            <span
              className={cn(
                "relative z-[1] grid size-[40px] shrink-0 place-items-center rounded-full border font-mono text-[14px] font-medium tnum",
                // A ring in the surface colour cuts the connector short of each disc; the active disc has its halo instead.
                s.status !== "active" && "ring-4 ring-surface",
                "transition-[background-color,border-color,color] duration-[var(--state-duration)] ease-[var(--ease-out-soft)]",
                s.status === "done" && "border-transparent bg-success-soft text-success-text",
                s.status === "active" && "border-transparent bg-surface text-white",
                s.status === "pending" && "border-line-strong bg-surface text-fg-2",
              )}
            >
              <ActiveDisc on={s.status === "active"} />
              <span className="relative grid place-items-center">
                {s.status === "done" ? <Check className="size-4" strokeWidth={2.5} aria-label="Done" /> : i + 1}
              </span>
            </span>
            <div className="flex min-w-0 flex-1 flex-col gap-3 pt-[9px] @[30rem]:flex-row @[30rem]:items-start @[30rem]:justify-between @[30rem]:gap-6">
              <div className="flex min-w-0 flex-col gap-1">
                <h3
                  className={cn("flex items-center gap-2 text-[15px] font-semibold leading-snug", s.status === "pending" ? "text-fg-2" : "text-fg")}
                >
                  {s.icon && (
                    <span className={cn("shrink-0 [&_svg]:size-5", s.status === "active" ? "text-accent-text" : "text-fg-3")}>{s.icon}</span>
                  )}
                  <span className="min-w-0 break-words">{s.title}</span>
                </h3>
                <p className={cn("max-w-[56ch] text-[14px] leading-relaxed", s.status === "pending" ? "text-fg-3" : "text-fg-2")}>{s.description}</p>
              </div>
              {s.status === "active" && s.action && <div className="shrink-0 @[30rem]:-mt-[3px]">{s.action}</div>}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

/** One connector segment on the disc axis; fills with the accent once the step above it is done. */
function Connector({ className, filled, delay }: { className: string; filled: boolean; delay: number }) {
  return (
    <span aria-hidden className={cn("absolute left-[35px] w-0.5 bg-line-strong", className)}>
      {filled && (
        <motion.span
          className="bg-accent absolute inset-0 origin-top"
          initial={{ scaleY: 0 }}
          animate={{ scaleY: 1 }}
          transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1], delay }}
        />
      )}
    </span>
  );
}
