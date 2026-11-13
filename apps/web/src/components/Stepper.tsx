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
 * 8px vertical and 16px side padding and a 40px circle at its top left, so all circles share one
 * centre axis at 36px from the row's left edge and 28px from its top. Each row except the last
 * draws the connector from its circle centre down by its own height, which lands exactly on the
 * next circle centre; rows touch, so the line is continuous. The active step lifts its text and
 * action into a raised card to the right of the circles, so the line never meets the card.
 * Segments after a done step fill with the accent, the rest are muted.
 */
export function Stepper({ steps, label = "Steps" }: { steps: Step[]; label?: string }) {
  return (
    <ol aria-label={label} className="flex flex-col">
      {steps.map((s, i) => {
        const last = i === steps.length - 1;
        const active = s.status === "active";
        return (
          <li key={s.title} aria-current={active ? "step" : undefined} className="relative flex gap-3 px-4 py-2">
            {!last && <Connector filled={s.status === "done"} delay={0.1 * i} />}
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
            <div
              className={cn(
                "flex min-w-0 flex-1 flex-col items-start gap-3 rounded-panel px-3 pb-3 pt-[9px]",
                "transition-[background-color,box-shadow] duration-200",
                // Every row carries the card's padding so text lines up; only the active one shows the card.
                active && "bg-surface shadow-[0_10px_28px_-16px_hsl(var(--shadow-color)/0.45)] dark:bg-surface-3/45",
              )}
            >
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
              {/* The action sits under the text so the description keeps the full width. */}
              {active && s.action && <div className="mb-1">{s.action}</div>}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

/** The connector from one circle centre to the next; fills with the accent once the step above it is done. */
function Connector({ filled, delay }: { filled: boolean; delay: number }) {
  return (
    <span aria-hidden className="absolute left-[35px] top-[28px] h-full w-0.5 bg-line-strong">
      {filled && (
        <motion.span
          className="bg-accent absolute inset-0 origin-top"
          initial={{ scaleY: 0 }}
          animate={{ scaleY: 1 }}
          transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1], delay }}
        />
      )}
    </span>
  );
}
