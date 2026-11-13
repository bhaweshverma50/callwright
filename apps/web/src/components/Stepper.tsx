import { Check } from "lucide-react";
import { motion } from "motion/react";
import type { ReactNode } from "react";
import { cn } from "./cn";

export type StepStatus = "done" | "active" | "pending";

export interface Step {
  title: string;
  description: ReactNode;
  status: StepStatus;
  /** Shown inside the active row (the step's primary action). */
  action?: ReactNode;
}

/**
 * Vertical stepper for a real sequence (numbered because order matters). No cards: the step you are
 * on stands out by its solid disc, full-ink title and its action; done steps fold to their title so
 * the eye lands on what is next. Geometry: every row starts with a 32px disc, so all discs share
 * one axis 16px from the left. Each row except the last draws the connector from its disc centre
 * down by its own height, which lands on the next disc centre; rows touch, so the line is
 * continuous, and a ring in the surface colour cuts it short of each disc. Segments below a done
 * step fill with the accent.
 */
export function Stepper({ steps, label = "Steps" }: { steps: Step[]; label?: string }) {
  return (
    <ol aria-label={label} className="flex flex-col">
      {steps.map((s, i) => {
        const last = i === steps.length - 1;
        return (
          <li key={s.title} aria-current={s.status === "active" ? "step" : undefined} className="relative flex gap-4 pb-7 last:pb-0">
            {!last && <Connector filled={s.status === "done"} delay={0.1 * i} />}
            <span
              className={cn(
                "relative z-[1] grid size-8 shrink-0 place-items-center rounded-full border font-mono text-[13px] font-medium tnum ring-4 ring-surface",
                "transition-[background-color,border-color,color,box-shadow] duration-[var(--state-duration)] ease-[var(--ease-out-soft)]",
                s.status === "done" && "border-transparent bg-success-soft text-success-text",
                // The current step: solid accent with a soft outer ring beyond the surface gap.
                s.status === "active" && "border-transparent bg-accent text-accent-fg shadow-[0_0_0_7px_var(--accent-soft)]",
                s.status === "pending" && "border-line-strong bg-surface text-fg-3",
              )}
            >
              {s.status === "done" ? <Check className="size-4" strokeWidth={2.5} aria-hidden /> : i + 1}
            </span>
            <div className="flex min-w-0 flex-1 flex-col items-start pt-[5px]">
              <div className="flex flex-wrap items-baseline gap-x-2.5">
                <h3 className={cn("min-w-0 break-words text-[15px] font-semibold leading-[22px]", s.status === "active" ? "text-fg" : "text-fg-2")}>
                  {s.title}
                </h3>
                {s.status === "done" && <span className="text-[13px] font-medium text-success-text">Done</span>}
              </div>
              {s.status !== "done" && (
                <p className={cn("mt-1 max-w-[56ch] text-[14px] leading-relaxed", s.status === "active" ? "text-fg-2" : "text-fg-3")}>
                  {s.description}
                </p>
              )}
              {s.status === "active" && s.action && <div className="mt-3.5">{s.action}</div>}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

/** The connector from one disc centre to the next; fills with the accent once the step above it is done. */
function Connector({ filled, delay }: { filled: boolean; delay: number }) {
  return (
    <span aria-hidden className="absolute left-[15px] top-4 h-full w-0.5 bg-line-strong">
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
