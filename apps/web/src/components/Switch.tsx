import * as RSw from "@radix-ui/react-switch";
import { useId, type ReactNode } from "react";
import { cn, focusRing } from "./cn";

export interface SwitchProps {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  label: ReactNode;
  description?: ReactNode;
  icon?: ReactNode;
  disabled?: boolean;
  className?: string;
}

/** Labelled on/off switch. State is announced as on or off; the label row explains the effect. */
export function Switch({ checked, onCheckedChange, label, description, icon, disabled, className }: SwitchProps) {
  const id = useId();
  return (
    <div className={cn("flex items-start justify-between gap-6", className)}>
      <div className="flex items-start gap-3">
        {icon && <span className="mt-0.5 text-fg-3 [&_svg]:size-[18px]">{icon}</span>}
        <div className="flex flex-col gap-0.5">
          <label htmlFor={id} className="cursor-pointer text-[13.5px] font-medium text-fg">
            {label}
          </label>
          {description && (
            <p id={`${id}-d`} className="text-[12.5px] leading-relaxed text-fg-3">
              {description}
            </p>
          )}
        </div>
      </div>
      <RSw.Root
        id={id}
        checked={checked}
        onCheckedChange={onCheckedChange}
        disabled={disabled}
        aria-describedby={description ? `${id}-d` : undefined}
        className={cn(
          "relative mt-0.5 inline-flex h-6 w-10 shrink-0 cursor-pointer items-center rounded-full border transition-colors duration-200",
          "border-line-strong bg-surface-3 data-[state=checked]:grad-action data-[state=checked]:border-transparent",
          "disabled:cursor-not-allowed disabled:opacity-50",
          focusRing,
        )}
      >
        <RSw.Thumb
          className={cn(
            "block size-[18px] translate-x-[2px] rounded-full bg-white shadow-1 transition-transform duration-200 ease-out",
            "data-[state=checked]:translate-x-[18px]",
          )}
        />
      </RSw.Root>
    </div>
  );
}
