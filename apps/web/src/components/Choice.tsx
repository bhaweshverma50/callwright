import { motion } from "motion/react";
import { useId, type KeyboardEvent, type ReactNode } from "react";
import { Check } from "lucide-react";
import { cn, focusRing } from "./cn";

/**
 * Arrow keys move the choice inside a radio group (WAI-ARIA radio pattern): the selected option is
 * the only tab stop, Left/Up and Right/Down select the previous or next enabled option.
 */
function onRadioKeys<T extends string>(
  e: KeyboardEvent<HTMLElement>,
  values: { value: T; disabled?: boolean }[],
  value: T,
  onChange: (v: T) => void,
) {
  const dir = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 0;
  if (!dir) return;
  e.preventDefault();
  const enabled = values.filter((v) => !v.disabled);
  const i = enabled.findIndex((v) => v.value === value);
  const next = enabled[(i + dir + enabled.length) % enabled.length];
  if (!next) return;
  onChange(next.value);
  const group = e.currentTarget;
  window.requestAnimationFrame(() => group.querySelector<HTMLElement>(`[data-value="${CSS.escape(next.value)}"]`)?.focus());
}

export interface SegmentOption<T extends string> {
  value: T;
  label: ReactNode;
  icon?: ReactNode;
  disabled?: boolean;
}

/**
 * A short set of mutually exclusive options shown side by side (who speaks first, a type filter).
 * The selected segment is a raised surface pill that slides between options.
 */
export function Segmented<T extends string>({
  value,
  onValueChange,
  options,
  id,
  size = "md",
  fill,
  className,
  ...aria
}: {
  value: T;
  onValueChange: (v: T) => void;
  options: SegmentOption<T>[];
  id?: string;
  size?: "sm" | "md";
  /** Stretch segments to the full width. */
  fill?: boolean;
  className?: string;
  "aria-label"?: string;
  "aria-labelledby"?: string;
  "aria-describedby"?: string;
}) {
  const layoutId = useId();
  return (
    <div
      id={id}
      role="radiogroup"
      aria-label={aria["aria-label"]}
      aria-labelledby={aria["aria-labelledby"]}
      aria-describedby={aria["aria-describedby"]}
      onKeyDown={(e) => onRadioKeys(e, options, value, onValueChange)}
      className={cn("inline-flex max-w-full rounded-control border border-line bg-surface-2 p-[3px]", fill && "flex w-full", className)}
    >
      {options.map((o) => {
        const on = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={on}
            data-value={o.value}
            tabIndex={on ? 0 : -1}
            disabled={o.disabled}
            onClick={() => onValueChange(o.value)}
            className={cn(
              "relative inline-flex min-w-0 cursor-pointer items-center justify-center gap-1.5 whitespace-nowrap rounded-[6px] px-3 font-medium transition-colors duration-150 [&_svg]:size-3.5",
              size === "sm" ? "h-7 text-[12.5px]" : "h-8 text-[13px]",
              fill && "flex-1",
              on ? "text-fg" : "text-fg-2 hover:text-fg",
              "disabled:cursor-not-allowed disabled:text-fg-3",
              focusRing,
            )}
          >
            {on && (
              <motion.span
                layoutId={layoutId}
                aria-hidden
                className="absolute inset-0 rounded-[6px] border border-line bg-surface shadow-1 dark:border-line-strong dark:bg-surface-3"
                transition={{ type: "spring", stiffness: 520, damping: 40 }}
              />
            )}
            <span className="relative inline-flex min-w-0 items-center gap-1.5">
              {o.icon && <span className={cn("shrink-0", on ? "text-accent-text" : "text-fg-3")}>{o.icon}</span>}
              <span className="truncate">{o.label}</span>
            </span>
          </button>
        );
      })}
    </div>
  );
}

export interface ChoiceOption<T extends string> {
  value: T;
  title: ReactNode;
  description?: ReactNode;
  icon?: ReactNode;
  /** Right side of the title row (price, badge). */
  meta?: ReactNode;
  /** Extra content under the description (bullets, an illustration). */
  children?: ReactNode;
  disabled?: boolean;
}

/**
 * Selectable cards for a choice that deserves a description (agent type, noise cancellation).
 * Selected state is a tinted surface, an accent outline all round and a check disc; never a side
 * stripe. Unselected cards lift on hover.
 */
export function ChoiceGroup<T extends string>({
  value,
  onValueChange,
  options,
  columns = 2,
  size = "md",
  className,
  id,
  ...aria
}: {
  value: T | null;
  onValueChange: (v: T) => void;
  options: ChoiceOption<T>[];
  columns?: 1 | 2 | 3;
  size?: "sm" | "md" | "lg";
  className?: string;
  id?: string;
  "aria-label"?: string;
  "aria-labelledby"?: string;
}) {
  const first = options.find((o) => !o.disabled)?.value;
  return (
    <div
      id={id}
      role="radiogroup"
      aria-label={aria["aria-label"]}
      aria-labelledby={aria["aria-labelledby"]}
      onKeyDown={(e) => onRadioKeys(e, options, (value ?? first) as T, onValueChange)}
      className={cn("@container", className)}
    >
      <div
        className={cn(
          "grid grid-cols-[minmax(0,1fr)] gap-3",
          columns === 2 && "@[34rem]:grid-cols-2",
          columns === 3 && "@[34rem]:grid-cols-2 @[52rem]:grid-cols-3",
        )}
      >
        {options.map((o) => {
          const on = o.value === value;
          return (
            <div
              key={o.value}
              role="radio"
              aria-checked={on}
              aria-disabled={o.disabled || undefined}
              data-value={o.value}
              data-disabled={o.disabled || undefined}
              tabIndex={o.disabled ? undefined : on || (value === null && o.value === first) ? 0 : -1}
              onClick={() => !o.disabled && onValueChange(o.value)}
              onKeyDown={(e) => {
                if ((e.key === " " || e.key === "Enter") && !o.disabled) {
                  e.preventDefault();
                  onValueChange(o.value);
                }
              }}
              className={cn(
                "group relative flex min-w-0 cursor-pointer flex-col items-stretch rounded-panel border text-left",
                "transition-[background-color,border-color,box-shadow,transform] duration-200 ease-[var(--ease-out-soft)]",
                size === "sm" ? "gap-1 px-3.5 py-3" : size === "lg" ? "gap-3 p-5" : "gap-1.5 p-4",
                on
                  ? "border-accent bg-accent-soft/45 shadow-[0_0_0_1px_var(--accent),0_12px_28px_-18px_rgb(51_70_232/0.55)]"
                  : "border-line bg-surface hover:-translate-y-0.5 hover:border-accent/45 hover:shadow-glow",
                "data-[disabled]:cursor-not-allowed data-[disabled]:opacity-60 data-[disabled]:hover:translate-y-0 data-[disabled]:hover:border-line data-[disabled]:hover:shadow-none",
                focusRing,
              )}
            >
              <span className="flex min-w-0 items-start gap-3">
                {o.icon && (
                  <span
                    className={cn(
                      "grid shrink-0 place-items-center rounded-control transition-colors duration-200",
                      size === "sm" ? "size-8 [&_svg]:size-4" : "size-10 [&_svg]:size-5",
                      on ? "grad-action text-white" : "bg-surface-2 text-accent-text",
                    )}
                  >
                    {o.icon}
                  </span>
                )}
                <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                  <span className="flex min-w-0 items-center justify-between gap-3">
                    <span className={cn("min-w-0 font-semibold text-fg", size === "lg" ? "text-[15.5px]" : "text-[13.5px]")}>{o.title}</span>
                    {o.meta != null && size !== "sm" && <span className="shrink-0 text-[12px] text-fg-3">{o.meta}</span>}
                  </span>
                  {o.description && (
                    <span className={cn("text-fg-2", size === "sm" ? "text-[12.5px] leading-snug" : "text-[13px] leading-relaxed")}>
                      {o.description}
                    </span>
                  )}
                  {o.meta != null && size === "sm" && (
                    <span className={cn("mt-0.5 text-[12px] text-fg-3", typeof o.meta === "string" && o.meta.startsWith("$") && "font-mono tnum")}>
                      {o.meta}
                    </span>
                  )}
                </span>
                <span
                  aria-hidden
                  className={cn(
                    "grid size-5 shrink-0 place-items-center rounded-full border transition-[background-color,border-color,transform] duration-200",
                    on ? "scale-100 border-transparent grad-action text-white" : "scale-90 border-line-strong bg-surface text-transparent",
                  )}
                >
                  <Check strokeWidth={3} className="size-3" />
                </span>
              </span>
              {o.children}
            </div>
          );
        })}
      </div>
    </div>
  );
}
