import { Check } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import type { ReactNode } from "react";
import { cn } from "./cn";

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
 * at 36px from the row edge. Each row except the last draws the connector from its circle centre
 * down by its own height, which lands exactly on the next circle centre; rows touch, so the line
 * is continuous. Segments after a done step fill with the action gradient, the rest are muted.
 */
export function Stepper({ steps, label = "Steps" }: { steps: Step[]; label?: string }) {
  return (
    <ol aria-label={label} className="@container flex flex-col">
      {steps.map((s, i) => {
        const last = i === steps.length - 1;
        const filled = s.status === "done";
        return (
          <li
            key={s.title}
            aria-current={s.status === "active" ? "step" : undefined}
            className={cn(
              "relative flex gap-4 rounded-panel p-4 transition-[background-color,box-shadow] duration-200",
              // Active row: a subtle full-row lift. No borders or side stripes.
              s.status === "active" && "bg-surface shadow-[0_10px_28px_-16px_hsl(var(--shadow-color)/0.45)] dark:bg-surface-3/45",
            )}
          >
            {!last && (
              <span aria-hidden className="absolute left-[35px] top-[36px] h-full w-0.5 bg-line-strong">
                {filled && (
                  <motion.span
                    className="grad-action absolute inset-0 origin-top"
                    initial={{ scaleY: 0 }}
                    animate={{ scaleY: 1 }}
                    transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1], delay: 0.1 * i }}
                  />
                )}
              </span>
            )}
            <span
              className={cn(
                "relative z-[1] grid size-[40px] shrink-0 place-items-center rounded-full font-mono text-[14px] font-medium tnum",
                s.status === "done" && "bg-success-soft text-success-text ring-4 ring-surface",
                s.status === "active" && "grad-action text-white",
                s.status === "pending" && "border border-line-strong bg-surface text-fg-2 ring-4 ring-surface",
              )}
            >
              {s.status === "active" && <Halo />}
              {s.status === "done" ? <Check className="size-4" strokeWidth={2.5} aria-label="Done" /> : i + 1}
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
                <p className={cn("max-w-[56ch] text-[13.5px] leading-relaxed", s.status === "pending" ? "text-fg-3" : "text-fg-2")}>
                  {s.description}
                </p>
              </div>
              {s.status === "active" && s.action && <div className="shrink-0 @[30rem]:-mt-[3px]">{s.action}</div>}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

/** Soft halo around the active step's disc; a static ring under reduced motion. */
function Halo() {
  const reduce = useReducedMotion();
  return (
    <motion.span
      aria-hidden
      className="pointer-events-none absolute -inset-1 rounded-full ring-4 ring-violet/25"
      initial={false}
      animate={reduce ? { opacity: 1, scale: 1 } : { opacity: [0.9, 0], scale: [1, 1.35] }}
      transition={reduce ? { duration: 0 } : { duration: 1.8, repeat: Infinity, ease: "easeOut" }}
    />
  );
}
