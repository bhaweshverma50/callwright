import * as RSw from "@radix-ui/react-switch";
import { useId, type ReactNode } from "react";
import { cn, focusRing } from "./cn";

export interface SwitchProps {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  label: ReactNode;
  description?: ReactNode;
  disabled?: boolean;
  className?: string;
}

/** Labelled on/off switch. The whole row is the click target; state is announced as on or off. */
export function Switch({ checked, onCheckedChange, label, description, disabled, className }: SwitchProps) {
  const id = useId();
  return (
    <div className={cn("flex items-start justify-between gap-6", className)}>
      <div className="flex flex-col gap-0.5">
        <label htmlFor={id} className="text-[13px] font-medium text-fg">
          {label}
        </label>
        {description && (
          <p id={`${id}-d`} className="text-[12.5px] text-fg-3">
            {description}
          </p>
        )}
      </div>
      <RSw.Root
        id={id}
        checked={checked}
        onCheckedChange={onCheckedChange}
        disabled={disabled}
        aria-describedby={description ? `${id}-d` : undefined}
        className={cn(
          "relative mt-0.5 inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full border transition-colors",
          "border-line-strong bg-surface-3 data-[state=checked]:border-accent data-[state=checked]:bg-accent",
          "disabled:cursor-not-allowed disabled:opacity-50",
          focusRing,
        )}
      >
        <RSw.Thumb
          className={cn(
            "block size-3.5 translate-x-0.5 rounded-full bg-surface shadow-panel transition-transform duration-150",
            "data-[state=checked]:translate-x-[18px] data-[state=checked]:bg-accent-fg",
          )}
        />
      </RSw.Root>
    </div>
  );
}
