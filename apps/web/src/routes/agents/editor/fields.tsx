/**
 * Building blocks shared by the editor sections. Every section is a Panel with the one card
 * anatomy (icon, title, one-line description, then rows); every row puts label and help on the
 * left and the control on the right, or stacks for wide controls (prompt, lists).
 */
import { CircleAlert, Info, TriangleAlert } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useState, type ReactNode } from "react";
import { FieldRow, InfoTip, Input, Panel, PanelRows, Slider, cn, type SliderMark } from "../../../components";
import type { ControlRange } from "../../../api/agents";
import { fieldId } from "../versions/versionLabels";
import { formatControl, parseNumber, snap } from "./formatters";
import type { AgentDraft } from "./useAgentDraft";

export function Section({
  icon,
  title,
  description,
  actions,
  children,
  id,
}: {
  icon: ReactNode;
  title: string;
  description: string;
  actions?: ReactNode;
  children: ReactNode;
  id?: string;
}) {
  return (
    <Panel as="section" title={title} description={description} icon={icon} actions={actions} bodyClassName="p-0" className="scroll-mt-24">
      <div id={id}>
        <PanelRows>{children}</PanelRows>
      </div>
    </Panel>
  );
}

/** Inline field error: animates in under the control and is announced. */
export function FieldError({ id, message }: { id?: string; message: string | null }) {
  return (
    <AnimatePresence initial={false}>
      {message && (
        <motion.p
          key={message}
          id={id}
          role="alert"
          initial={{ opacity: 0, y: -3 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.16 }}
          className="flex w-full items-start gap-1.5 text-left text-[12.5px] text-danger-text"
        >
          <CircleAlert className="mt-px size-3.5 shrink-0" strokeWidth={2} aria-hidden />
          <span>{message}</span>
        </motion.p>
      )}
    </AnimatePresence>
  );
}

/** A quiet note under a control (helper text that is not an error). */
export function Note({ children, tone = "neutral", id }: { children: ReactNode; tone?: "neutral" | "warning" | "accent"; id?: string }) {
  const Icon = tone === "warning" ? TriangleAlert : Info;
  return (
    <p
      id={id}
      className={cn(
        "flex w-full items-start gap-1.5 text-left text-[12.5px] leading-snug",
        tone === "warning" ? "text-warning-text" : tone === "accent" ? "text-accent-text" : "text-fg-3",
      )}
    >
      <Icon className="mt-px size-3.5 shrink-0" aria-hidden />
      <span>{children}</span>
    </p>
  );
}

/** Full-width row for wide controls: label and actions on one line, then the control. */
export function StackRow({
  icon,
  label,
  htmlFor,
  description,
  hint,
  actions,
  children,
}: {
  icon?: ReactNode;
  label: ReactNode;
  htmlFor?: string;
  description?: ReactNode;
  hint?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-3 px-5 py-4">
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <div className="flex min-w-0 items-start gap-3">
          {icon && <span className="mt-[1px] shrink-0 text-fg-3 [&_svg]:size-4">{icon}</span>}
          <div className="flex min-w-0 flex-col gap-0.5">
            <span className="flex items-center gap-1.5">
              {htmlFor ? (
                <label htmlFor={htmlFor} className="cursor-pointer text-[13.5px] font-medium text-fg">
                  {label}
                </label>
              ) : (
                <span className="text-[13.5px] font-medium text-fg">{label}</span>
              )}
              {hint && <InfoTip label={`About ${typeof label === "string" ? label.toLowerCase() : "this setting"}`}>{hint}</InfoTip>}
            </span>
            {description && <p className="text-[12.5px] leading-relaxed text-fg-3">{description}</p>}
          </div>
        </div>
        {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
      </div>
      <div className="flex min-w-0 flex-col gap-2 sm:pl-7">{children}</div>
    </div>
  );
}

/** The current value of a slider, in a fixed-width mono pill so it never shifts the layout. */
export function ValuePill({ children, muted }: { children: ReactNode; muted?: boolean }) {
  return (
    <span
      className={cn(
        "inline-flex h-6 min-w-[64px] items-center justify-center rounded-inline px-2 font-mono text-[12.5px] tnum",
        muted ? "bg-surface-2 text-fg-3" : "bg-accent-soft text-accent-text",
      )}
    >
      {children}
    </span>
  );
}

export function controlFor(controls: ControlRange[] | undefined, path: string): ControlRange | undefined {
  return controls?.find((c) => c.path === path);
}

/**
 * A slider row driven by the catalog control range (FR-047): min, max, step and the label format
 * come from `controls`, so the label is always the stored value.
 */
export function SliderRow({
  draft,
  control,
  pointer,
  value,
  onChange,
  icon,
  description,
  hint,
  marks,
  disabled,
  disabledNote,
  label,
}: {
  draft: AgentDraft;
  control: ControlRange | undefined;
  pointer: string;
  value: number;
  onChange: (v: number) => void;
  icon?: ReactNode;
  description?: ReactNode;
  hint?: ReactNode;
  marks?: SliderMark[];
  disabled?: boolean;
  disabledNote?: ReactNode;
  label?: string;
}) {
  const id = fieldId(pointer);
  const error = draft.errorFor(pointer);
  if (!control) return null;
  const text = formatControl(control, value);
  return (
    <FieldRow icon={icon} label={label ?? control.label} htmlFor={id} description={description} hint={hint}>
      <div className="flex w-full flex-col gap-1.5">
        <div className="flex justify-end">
          <ValuePill muted={disabled}>{text}</ValuePill>
        </div>
        <Slider
          id={id}
          value={value}
          min={control.min}
          max={control.max}
          step={control.step}
          disabled={disabled}
          marks={marks}
          valueText={() => text}
          aria-describedby={error ? `${id}-err` : undefined}
          onValueChange={(v) => onChange(snap(v, control.min, control.step))}
          onValueCommit={() => draft.touch(pointer)}
        />
        {disabled && disabledNote ? <Note>{disabledNote}</Note> : null}
        <FieldError id={`${id}-err`} message={error} />
      </div>
    </FieldRow>
  );
}

/**
 * A number typed in a display unit (minutes, seconds) and stored in another (seconds, ms). Text
 * that is not a number is a local error; a number is converted and validated by the platform.
 */
export function UnitNumberInput({
  draft,
  pointer,
  stored,
  toDisplay,
  fromDisplay,
  unit,
  step,
  min,
  helper,
  disabled,
}: {
  draft: AgentDraft;
  pointer: string;
  stored: number;
  toDisplay: (stored: number) => number;
  fromDisplay: (display: number) => number;
  unit: string;
  step?: number;
  min?: number;
  /** Exact reading of the stored value ("Rings for 1.5 s before the agent answers"). */
  helper?: (stored: number) => ReactNode;
  disabled?: boolean;
}) {
  const id = fieldId(pointer);
  const [text, setText] = useState(() => String(toDisplay(stored)));
  // Follow outside changes (discard, restore, assistant) without fighting the user's typing.
  useEffect(() => {
    setText((t) => (parseNumber(t) !== null && fromDisplay(parseNumber(t)!) === stored ? t : String(toDisplay(stored))));
  }, [stored, toDisplay, fromDisplay]);
  const error = draft.errorFor(pointer);
  return (
    <div className="flex w-full flex-col gap-1.5">
      <Input
        id={id}
        inputMode="decimal"
        type="text"
        value={text}
        step={step}
        min={min}
        disabled={disabled}
        aria-invalid={Boolean(error)}
        aria-describedby={`${id}-help`}
        suffix={<span className="text-[12.5px]">{unit}</span>}
        onChange={(e) => {
          const t = e.target.value;
          setText(t);
          const n = parseNumber(t);
          if (n === null) {
            draft.setLocalError(pointer, t.trim() ? "Enter a number." : "Enter a value.");
          } else {
            draft.setLocalError(pointer, null);
            draft.update((c) => setAt(c, pointer, fromDisplay(n)));
          }
        }}
        onBlur={() => draft.touch(pointer)}
      />
      {error ? (
        <FieldError id={`${id}-help`} message={error} />
      ) : helper ? (
        <p id={`${id}-help`} className="w-full text-left text-[12.5px] text-fg-3 @[34rem]:text-right">
          {helper(stored)}
        </p>
      ) : null}
    </div>
  );
}

/** Sets a value at a plain JSON pointer ("/call_behavior/ring_duration_ms") on a draft. */
export function setAt(target: object, pointer: string, value: unknown) {
  const parts = pointer.split("/").filter(Boolean);
  let o = target as Record<string, unknown>;
  for (const p of parts.slice(0, -1)) o = o[p] as Record<string, unknown>;
  o[parts[parts.length - 1]!] = value;
}
