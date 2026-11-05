import { forwardRef, useId, type InputHTMLAttributes, type ReactNode, type TextareaHTMLAttributes } from "react";
import { CircleAlert } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { cn, focusRing } from "./cn";
import { joinIds, useFieldRowAria } from "./Panel";

export interface FieldProps {
  label: ReactNode;
  /** Helper text under the control; replaced by the error when there is one. */
  hint?: ReactNode;
  error?: string | null;
  /** Visually hide the label but keep it for assistive tech. */
  hideLabel?: boolean;
  /** Right side of the label row (counter, link). */
  aside?: ReactNode;
  className?: string;
  children: (ids: { id: string; describedBy: string | undefined; invalid: boolean }) => ReactNode;
}

/** Label above, control, then hint or error below (one place for form layout rules). */
export function Field({ label, hint, error, hideLabel, aside, className, children }: FieldProps) {
  const id = useId();
  const hintId = `${id}-hint`;
  const invalid = Boolean(error);
  const describedBy = hint || error ? hintId : undefined;
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <div className={cn("flex items-baseline justify-between gap-3", hideLabel && "sr-only")}>
        <label htmlFor={id} className="text-[13px] font-medium text-fg">
          {label}
        </label>
        {aside}
      </div>
      {children({ id, describedBy, invalid })}
      <AnimatePresence initial={false} mode="wait">
        {error ? (
          <motion.p
            key="error"
            id={hintId}
            role="alert"
            initial={{ opacity: 0, y: -3 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.16 }}
            className="flex items-start gap-1.5 text-[13px] text-danger-text"
          >
            <CircleAlert className="mt-px size-3.5 shrink-0" strokeWidth={2} aria-hidden />
            {error}
          </motion.p>
        ) : hint ? (
          <p key="hint" id={hintId} className="text-[13px] text-fg-3">
            {hint}
          </p>
        ) : null}
      </AnimatePresence>
    </div>
  );
}

export const controlBase = cn(
  "w-full rounded-control border bg-surface text-[14px] text-fg placeholder:text-fg-3",
  "border-line-strong hover:border-fg-3 transition-[border-color,box-shadow] duration-150",
  "focus-visible:border-accent focus-visible:shadow-[0_0_0_4px_var(--accent-soft)]",
  "disabled:cursor-not-allowed disabled:bg-surface-2 disabled:text-fg-3",
  "aria-[invalid=true]:border-danger aria-[invalid=true]:hover:border-danger",
  focusRing,
);

export interface InputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "prefix"> {
  /** Static text or icon inside the left edge (for example "$"). */
  prefix?: ReactNode;
  suffix?: ReactNode;
  inputSize?: "sm" | "md" | "lg";
}

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input({ prefix, suffix, inputSize = "md", className, ...props }, ref) {
  const row = useFieldRowAria(props.id);
  const rest = { ...props, "aria-describedby": joinIds(row.describedBy, props["aria-describedby"]) };
  const h = inputSize === "sm" ? "h-8" : inputSize === "lg" ? "h-11 text-[14px]" : "h-9";
  if (!prefix && !suffix) return <input ref={ref} className={cn(controlBase, h, "px-3", className)} {...rest} />;
  return (
    <div className={cn("relative flex items-center", className)}>
      {prefix && (
        <span className="pointer-events-none absolute left-3 flex items-center font-mono text-[13px] text-fg-3 [&_svg]:size-4" aria-hidden>
          {prefix}
        </span>
      )}
      <input
        ref={ref}
        className={cn(controlBase, h, prefix ? (typeof prefix === "string" ? "pl-7" : "pl-9") : "px-3", suffix ? "pr-10" : "pr-3")}
        {...rest}
      />
      {suffix && <span className="absolute right-2.5 flex items-center text-fg-3">{suffix}</span>}
    </div>
  );
});

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(function Textarea({ className, ...rest }, ref) {
  const row = useFieldRowAria(rest.id);
  return (
    <textarea
      ref={ref}
      className={cn(controlBase, "min-h-24 px-3 py-2 leading-relaxed", className)}
      {...rest}
      aria-describedby={joinIds(row.describedBy, rest["aria-describedby"])}
    />
  );
});
