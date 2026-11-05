import * as RT from "@radix-ui/react-tabs";
import { motion } from "motion/react";
import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from "react";
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
  /** Many tabs in a narrow column (agent editor): tighter spacing, and icons drop out when the row
   * is narrower than 45rem so the labels still fit. */
  density?: "default" | "compact";
  "aria-label"?: string;
}

/** Which ends of a sideways-scrolling row have hidden tabs, for the fade hint. */
function useOverflowEdges() {
  const ref = useRef<HTMLDivElement>(null);
  const [edges, setEdges] = useState({ start: false, end: false });
  const measure = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    const start = el.scrollLeft > 1;
    const end = el.scrollLeft + el.clientWidth < el.scrollWidth - 1;
    setEdges((e) => (e.start === start && e.end === end ? e : { start, end }));
  }, []);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    for (const child of Array.from(el.children)) ro.observe(child);
    return () => ro.disconnect();
  }, [measure]);
  return { ref, edges, measure };
}

const FADE_PX = 32;
const FADE = `${FADE_PX - 4}px`;

/** Underline tabs with a sliding cobalt marker. Arrow keys move between tabs (Radix roving focus).
 * The marker sits inside its tab: the list scrolls sideways, which clips anything below it. */
export function Tabs({ value, onValueChange, items, children, className, density = "default", ...aria }: TabsProps) {
  const layoutId = useId();
  const { ref, edges, measure } = useOverflowEdges();
  const compact = density === "compact";
  // Tabs hidden past an edge fade out there, so a cut-off row reads as scrollable, not clipped.
  const mask =
    edges.start || edges.end
      ? `linear-gradient(to right, ${edges.start ? "transparent" : "#000"}, #000 ${FADE}, #000 calc(100% - ${FADE}), ${edges.end ? "transparent" : "#000"})`
      : undefined;
  // Keep the active tab in view inside the row, clear of the fade (sideways only; never scrolls the page).
  useEffect(() => {
    const frame = requestAnimationFrame(() => {
      const list = ref.current;
      const tab = list?.querySelector<HTMLElement>('[data-state="active"]');
      if (!list || !tab || list.scrollWidth <= list.clientWidth) return;
      const box = list.getBoundingClientRect();
      const t = tab.getBoundingClientRect();
      if (t.left < box.left + FADE_PX) list.scrollLeft += t.left - box.left - FADE_PX;
      else if (t.right > box.right - FADE_PX) list.scrollLeft += t.right - box.right + FADE_PX;
    });
    return () => cancelAnimationFrame(frame);
  }, [value, ref]);
  return (
    <RT.Root value={value} onValueChange={onValueChange} className={cn(compact && "@container", className)}>
      <RT.List
        ref={ref}
        onScroll={measure}
        aria-label={aria["aria-label"]}
        style={mask ? { maskImage: mask, WebkitMaskImage: mask } : undefined}
        className="flex gap-6 overflow-x-auto border-b border-line [scrollbar-width:none]"
      >
        {items.map((t) => (
          <RT.Trigger
            key={t.value}
            value={t.value}
            disabled={t.disabled}
            className={cn(
              "relative flex h-10 shrink-0 cursor-pointer items-center gap-2 whitespace-nowrap text-[14px] text-fg-2 transition-colors [&_svg]:size-4",
              compact && "[&>svg:first-child]:hidden @[45rem]:[&>svg:first-child]:block",
              "hover:text-fg data-[state=active]:font-medium data-[state=active]:text-fg",
              "disabled:cursor-not-allowed disabled:text-fg-3",
              focusRing,
            )}
          >
            {t.icon}
            {t.label}
            {t.count != null && <span className="font-mono text-[12px] text-fg-3 tnum">{t.count}</span>}
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
                className="bg-accent absolute inset-x-0 bottom-0 h-0.5 rounded-full"
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
    // Radix makes the panel a tab stop (after the tab list); keyboard users see where they landed.
    <RT.Content value={value} className={cn("rounded-control pt-5 data-[state=active]:animate-fade-in", focusRing, className)}>
      {children}
    </RT.Content>
  );
}
