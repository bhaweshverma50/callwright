import { forwardRef, useId, type InputHTMLAttributes, type ReactNode, type TextareaHTMLAttributes } from "react";
import { WarningCircle } from "@phosphor-icons/react";
import { cn, focusRing } from "./cn";

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
        <label htmlFor={id} className="text-[12.5px] font-medium text-fg">
          {label}
        </label>
        {aside}
      </div>
      {children({ id, describedBy, invalid })}
      {error ? (
        <p id={hintId} role="alert" className="flex items-start gap-1.5 text-[12.5px] text-danger-text">
          <WarningCircle weight="fill" className="mt-px size-3.5 shrink-0" aria-hidden />
          {error}
        </p>
      ) : hint ? (
        <p id={hintId} className="text-[12.5px] text-fg-3">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

export const controlBase = cn(
  "w-full rounded-control border bg-surface text-[13px] text-fg placeholder:text-fg-3",
  "border-line-strong hover:border-fg-3 transition-colors",
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

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { prefix, suffix, inputSize = "md", className, ...rest },
  ref,
) {
  const h = inputSize === "sm" ? "h-7" : inputSize === "lg" ? "h-10 text-sm" : "h-8";
  if (!prefix && !suffix) return <input ref={ref} className={cn(controlBase, h, "px-2.5", className)} {...rest} />;
  return (
    <div className={cn("relative flex items-center", className)}>
      {prefix && (
        <span className="pointer-events-none absolute left-2.5 font-mono text-[13px] text-fg-3" aria-hidden>
          {prefix}
        </span>
      )}
      <input ref={ref} className={cn(controlBase, h, prefix ? "pl-6" : "px-2.5", suffix ? "pr-10" : "pr-2.5")} {...rest} />
      {suffix && <span className="absolute right-2 flex items-center text-fg-3">{suffix}</span>}
    </div>
  );
});

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(function Textarea(
  { className, ...rest },
  ref,
) {
  return <textarea ref={ref} className={cn(controlBase, "min-h-24 px-2.5 py-2 leading-relaxed", className)} {...rest} />;
});
