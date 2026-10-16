import * as RT from "@radix-ui/react-tabs";
import { motion } from "motion/react";
import { useId, type ReactNode } from "react";
import { cn, focusRing } from "./cn";

export interface TabItem {
  value: string;
  label: ReactNode;
  icon?: ReactNode;
  /** Small count after the label, in mono. */
  count?: number;
  /** Count of problems in this tab, shown as a small danger pill (validation). */
  alerts?: number;
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

/** Underline tabs with a sliding cobalt marker. Arrow keys move between tabs (Radix roving focus). */
export function Tabs({ value, onValueChange, items, children, className, ...aria }: TabsProps) {
  const layoutId = useId();
  return (
    <RT.Root value={value} onValueChange={onValueChange} className={className}>
      <RT.List aria-label={aria["aria-label"]} className="flex gap-6 overflow-x-auto border-b border-line [scrollbar-width:none]">
        {items.map((t) => (
          <RT.Trigger
            key={t.value}
            value={t.value}
            disabled={t.disabled}
            className={cn(
              "relative -mb-px flex h-10 shrink-0 cursor-pointer items-center gap-2 whitespace-nowrap text-[13.5px] text-fg-2 transition-colors [&_svg]:size-4",
              "hover:text-fg data-[state=active]:font-medium data-[state=active]:text-fg",
              "disabled:cursor-not-allowed disabled:text-fg-3",
              focusRing,
            )}
          >
            {t.icon}
            {t.label}
            {t.count != null && <span className="font-mono text-[11.5px] text-fg-3 tnum">{t.count}</span>}
            {t.alerts ? (
              <span className="grid h-[18px] min-w-[18px] place-items-center rounded-full bg-danger-soft px-1 font-mono text-[11px] font-medium text-danger-text tnum">
                <span className="sr-only">, problems: </span>
                {t.alerts}
              </span>
            ) : null}
            {value === t.value && (
              <motion.span
                layoutId={layoutId}
                aria-hidden
                className="grad-action absolute inset-x-0 -bottom-px h-0.5 rounded-full"
                transition={{ type: "spring", stiffness: 500, damping: 40 }}
              />
            )}
          </RT.Trigger>
        ))}
      </RT.List>
      {children}
    </RT.Root>
  );
}

export function TabPanel({ value, children, className }: { value: string; children: ReactNode; className?: string }) {
  return (
    <RT.Content value={value} className={cn("pt-5 outline-none data-[state=active]:animate-fade-in", className)}>
      {children}
    </RT.Content>
  );
}
