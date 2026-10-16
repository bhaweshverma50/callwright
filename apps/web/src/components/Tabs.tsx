import * as RT from "@radix-ui/react-tabs";
import type { ReactNode } from "react";
import { cn, focusRing } from "./cn";

export interface TabItem {
  value: string;
  label: ReactNode;
  /** Small count after the label, in mono. */
  count?: number;
  disabled?: boolean;
}

export interface TabsProps {
  value: string;
  onValueChange: (value: string) => void;
  items: TabItem[];
  children: ReactNode;
  className?: string;
  "aria-label"?: string;
}

/** Underline tabs. Arrow keys move between tabs (Radix roving focus). */
export function Tabs({ value, onValueChange, items, children, className, ...aria }: TabsProps) {
  return (
    <RT.Root value={value} onValueChange={onValueChange} className={className}>
      <RT.List aria-label={aria["aria-label"]} className="flex gap-5 border-b border-line">
        {items.map((t) => (
          <RT.Trigger
            key={t.value}
            value={t.value}
            disabled={t.disabled}
            className={cn(
              "relative -mb-px flex h-9 items-center gap-1.5 border-b-2 border-transparent text-[13px] text-fg-2 transition-colors",
              "hover:text-fg data-[state=active]:border-accent data-[state=active]:font-medium data-[state=active]:text-fg",
              "disabled:cursor-not-allowed disabled:text-fg-3",
              focusRing,
            )}
          >
            {t.label}
            {t.count != null && <span className="font-mono text-[11px] text-fg-3 tnum">{t.count}</span>}
          </RT.Trigger>
        ))}
      </RT.List>
      {children}
    </RT.Root>
  );
}

export function TabPanel({ value, children, className }: { value: string; children: ReactNode; className?: string }) {
  return (
    <RT.Content value={value} className={cn("pt-5 outline-none", className)}>
      {children}
    </RT.Content>
  );
}
