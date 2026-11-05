import * as RSw from "@radix-ui/react-switch";
import { useId, type ReactNode } from "react";
import { cn, focusRing } from "./cn";
import { joinIds, useFieldRowAria } from "./Panel";

export interface SwitchControlProps {
  id?: string;
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  disabled?: boolean;
  describedBy?: string;
  "aria-label"?: string;
  className?: string;
}

/**
 * The bare on/off control. Geometry is fixed in px so it never depends on the root font size:
 * 40x24 track with a 1px border (border-box), 18px thumb, 2px inset on every side.
 * Thumb x: off = 2px; on = 40 - 2 (borders) - 18 (thumb) - 2 (inset) = 18px.
 */
export function SwitchControl({ id, checked, onCheckedChange, disabled, describedBy, className, ...aria }: SwitchControlProps) {
  const row = useFieldRowAria(id);
  return (
    <RSw.Root
      id={id}
      checked={checked}
      onCheckedChange={onCheckedChange}
      disabled={disabled}
      aria-describedby={joinIds(row.describedBy, describedBy)}
      aria-label={aria["aria-label"]}
      className={cn(
        "relative box-border inline-flex h-[24px] w-[40px] shrink-0 cursor-pointer items-center overflow-hidden rounded-full border p-0 transition-[background-color,border-color] duration-200",
        "border-line-strong bg-surface-3 hover:border-fg-3 data-[state=checked]:bg-accent data-[state=checked]:border-transparent",
        "disabled:cursor-not-allowed disabled:opacity-50",
        focusRing,
        className,
      )}
    >
      <RSw.Thumb
        className={cn(
          "pointer-events-none block size-[18px] translate-x-[2px] rounded-full bg-white shadow-[0_1px_2px_rgb(14_16_48/0.3)] transition-transform duration-200 ease-out",
          "data-[state=checked]:translate-x-[18px]",
        )}
      />
    </RSw.Root>
  );
}

export interface SwitchProps {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  label: ReactNode;
  description?: ReactNode;
  icon?: ReactNode;
  disabled?: boolean;
  className?: string;
}

/** Labelled on/off switch row. State is announced as on or off; the label row explains the effect. */
export function Switch({ checked, onCheckedChange, label, description, icon, disabled, className }: SwitchProps) {
  const id = useId();
  return (
    <div className={cn("flex items-start justify-between gap-6", className)}>
      <div className="flex items-start gap-3">
        {icon && <span className="mt-0.5 text-fg-3 [&_svg]:size-4">{icon}</span>}
        <div className="flex flex-col gap-0.5">
          <label htmlFor={id} className="cursor-pointer text-[14px] font-medium text-fg">
            {label}
          </label>
          {description && (
            <p id={`${id}-d`} className="text-[13px] leading-relaxed text-fg-3">
              {description}
            </p>
          )}
        </div>
      </div>
      <SwitchControl
        id={id}
        checked={checked}
        onCheckedChange={onCheckedChange}
        disabled={disabled}
        describedBy={description ? `${id}-d` : undefined}
        className="mt-0.5"
      />
    </div>
  );
}
