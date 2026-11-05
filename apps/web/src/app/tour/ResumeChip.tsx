import { Compass, Play, X } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import { createPortal } from "react-dom";
import { Button, IconButton, EASE_OUT_SOFT } from "../../components";
import { COUNTED, STEPS } from "./steps";

/**
 * A paused tour (Esc, the pause button, or a tour in progress found on sign-in): a small chip at
 * the foot of the page with Resume and End. It sits clear of the assistant dock (above it on phones).
 */
export function ResumeChip({ index, onResume, onEnd }: { index: number; onResume: () => void; onEnd: () => void }) {
  const reduce = useReducedMotion() ?? false;
  const step = STEPS[index]!;
  const where = step.id === "done" ? "Last step" : `Step ${index + 1} of ${COUNTED}`;
  return createPortal(
    <motion.div
      role="region"
      aria-label="Guided setup paused"
      data-tour-ui
      initial={reduce ? false : { opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.32, ease: EASE_OUT_SOFT }}
      className="fixed inset-x-4 bottom-[76px] z-[45] flex items-center gap-3 rounded-full border border-line bg-surface/95 py-1.5 pl-1.5 pr-2 shadow-pop backdrop-blur-md sm:inset-x-auto sm:bottom-4 sm:left-4 sm:max-w-[calc(100vw-280px)] lg:left-1/2 lg:-translate-x-1/2"
    >
      <span className="grid size-8 shrink-0 place-items-center rounded-full bg-accent text-white">
        <Compass className="size-4" aria-hidden />
      </span>
      <span className="flex min-w-0 flex-1 flex-col leading-tight">
        <span className="truncate text-[13px] font-medium text-fg">Guided setup paused</span>
        <span className="truncate text-[12px] text-fg-3">
          {where}: {step.title}
        </span>
      </span>
      <Button variant="primary" size="sm" icon={<Play aria-hidden />} onClick={onResume}>
        Resume
      </Button>
      <IconButton label="End the tour" className="size-8" onClick={onEnd}>
        <X className="size-4" aria-hidden />
      </IconButton>
    </motion.div>,
    document.body,
  );
}
