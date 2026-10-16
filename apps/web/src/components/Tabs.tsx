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
      <RT.List aria-label={aria["aria-label"]} className="flex gap-6 border-b border-line">
        {items.map((t) => (
          <RT.Trigger
            key={t.value}
            value={t.value}
            disabled={t.disabled}
            className={cn(
              "relative -mb-px flex h-10 cursor-pointer items-center gap-2 text-[13.5px] text-fg-2 transition-colors [&_svg]:size-4",
              "hover:text-fg data-[state=active]:font-medium data-[state=active]:text-fg",
              "disabled:cursor-not-allowed disabled:text-fg-3",
              focusRing,
            )}
          >
            {t.icon}
            {t.label}
            {t.count != null && <span className="font-mono text-[11.5px] text-fg-3 tnum">{t.count}</span>}
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
