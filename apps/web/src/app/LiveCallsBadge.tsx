import { AnimatePresence, motion } from "motion/react";
import { useLiveCalls } from "../api/live";
import { cn } from "../components";

/**
 * The live count on the sidebar's Calls item, from the shared live query. Expanded: a small chip
 * with the pulsing on-air dot and the count. On the icon rail: the dot alone at the icon's corner.
 * Nothing shows while no call is on air.
 */
export function LiveCallsBadge({ expanded }: { expanded: boolean }) {
  const n = useLiveCalls().data?.count ?? 0;
  const label = `${n} ${n === 1 ? "call" : "calls"} on air`;
  return (
    <AnimatePresence initial={false}>
      {n > 0 && (
        <motion.span
          key="live"
          initial={{ opacity: 0, scale: 0.85 }}
          animate={{ opacity: 1, scale: 1 }}
          exit={{ opacity: 0, scale: 0.85 }}
          transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }}
          className={cn(
            "pointer-events-none flex items-center",
            expanded ? "ml-auto h-5 shrink-0 gap-1.5 rounded-full border border-line bg-surface pl-1.5 pr-2 shadow-1" : "absolute right-1.5 top-1.5",
          )}
          data-testid="live-calls-badge"
        >
          <span className="relative grid size-2 place-items-center" aria-hidden>
            <span className="on-air-pulse absolute inset-0 rounded-full bg-on-air animate-on-air [--halo-peak:0.6] [--halo-to:2.2]" />
            <span className={cn("relative size-2 rounded-full bg-on-air", !expanded && "ring-2 ring-sidebar")} />
          </span>
          {expanded && (
            <span className="font-mono text-[12px] font-medium leading-none text-fg tnum" aria-hidden>
              {n}
            </span>
          )}
          <span className="sr-only">{label}</span>
        </motion.span>
      )}
    </AnimatePresence>
  );
}
