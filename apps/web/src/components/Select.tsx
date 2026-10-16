import * as RS from "@radix-ui/react-select";
import { Check, ChevronDown } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "./cn";
import { controlBase } from "./Field";

export interface SelectOption {
  value: string;
  label: ReactNode;
  /** Right-aligned secondary text (rate, count). Rendered in mono. */
  meta?: ReactNode;
  disabled?: boolean;
}

export interface SelectGroup {
  label: string;
  options: SelectOption[];
}

export interface SelectProps {
  id?: string;
  value: string | undefined;
  onValueChange: (value: string) => void;
  options?: SelectOption[];
  groups?: SelectGroup[];
  placeholder?: string;
  disabled?: boolean;
  invalid?: boolean;
  describedBy?: string;
  size?: "sm" | "md";
  className?: string;
  "aria-label"?: string;
}

/** Single-choice select on Radix: keyboard typeahead, arrow keys, Escape to close. */
export function Select({
  id,
  value,
  onValueChange,
  options,
  groups,
  placeholder = "Choose",
  disabled,
  invalid,
  describedBy,
  size = "md",
  className,
  ...aria
}: SelectProps) {
  const allGroups: SelectGroup[] = groups ?? [{ label: "", options: options ?? [] }];
  return (
    <RS.Root value={value} onValueChange={onValueChange} disabled={disabled}>
      <RS.Trigger
        id={id}
        aria-invalid={invalid || undefined}
        aria-describedby={describedBy}
        aria-label={aria["aria-label"]}
        className={cn(
          controlBase,
          "inline-flex items-center justify-between gap-2 px-2.5 text-left data-[placeholder]:text-fg-3",
          size === "sm" ? "h-8" : "h-9",
          className,
        )}
      >
        <span className="truncate">
          <RS.Value placeholder={placeholder} />
        </span>
        <RS.Icon>
          <ChevronDown className="size-4 text-fg-3" aria-hidden />
        </RS.Icon>
      </RS.Trigger>
      <RS.Portal>
        <RS.Content
          position="popper"
          sideOffset={4}
          className={cn(
            "z-50 max-h-[min(360px,var(--radix-select-content-available-height))] min-w-[var(--radix-select-trigger-width)] overflow-hidden",
            "rounded-panel border border-line bg-surface shadow-pop animate-pop-in data-[state=closed]:animate-fade-in",
          )}
        >
          <RS.Viewport className="p-1">
            {allGroups.map((g, gi) => (
              <RS.Group key={g.label || gi}>
                {g.label && (
                  <RS.Label className="px-2 pb-1 pt-2 text-[12px] font-medium text-fg-3">
                    {g.label}
                  </RS.Label>
                )}
                {g.options.map((o) => (
                  <RS.Item
                    key={o.value}
                    value={o.value}
                    disabled={o.disabled}
                    className={cn(
                      "relative flex h-9 cursor-pointer select-none items-center gap-3 rounded-[6px] pl-7 pr-2 text-[13px] text-fg outline-none",
                      "data-[highlighted]:bg-accent-soft/60 data-[disabled]:text-fg-3",
                    )}
                  >
                    <RS.ItemIndicator className="absolute left-2 inline-flex">
                      <Check strokeWidth={2.5} className="size-3.5 text-accent-text" aria-hidden />
                    </RS.ItemIndicator>
                    <RS.ItemText>{o.label}</RS.ItemText>
                    {o.meta != null && <span className="ml-auto font-mono text-[11.5px] text-fg-3 tnum">{o.meta}</span>}
                  </RS.Item>
                ))}
              </RS.Group>
            ))}
          </RS.Viewport>
        </RS.Content>
      </RS.Portal>
    </RS.Root>
  );
}
