import { Bot, Check, ChevronLeft, Pause, PhoneCall, PhoneForwarded, ListChecks, Wand2 } from "lucide-react";
import { AnimatePresence, motion, useAnimationControls, useReducedMotion } from "motion/react";
import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type RefObject } from "react";
import { createPortal } from "react-dom";
import { Link } from "react-router";
import { Button, IconButton, cn, focusRing, EASE_OUT_SOFT } from "../../components";
import { COUNTED, STEPS, type TourStep } from "./steps";

export interface StepProgress {
  /** The step asks for an action the user has not done yet. */
  waiting: boolean;
  /** The step's action is done (now, or already before the step opened). */
  done: boolean;
}

/** How long a step looks for its control before it shows its text without a spotlight. */
export const TARGET_TIMEOUT_MS = 4000;
const PAD = 6;
const GAP = 14;
const EDGE = 12;
const SHEET_BELOW = 640;

interface Box {
  top: number;
  left: number;
  width: number;
  height: number;
}

function isVisible(el: Element): boolean {
  if (!el.isConnected) return false;
  const r = el.getBoundingClientRect();
  // jsdom lays nothing out; there every connected element counts as visible.
  return r.width > 0 || r.height > 0 || navigator.userAgent.includes("jsdom");
}

function findTarget(selectors: string[] | undefined): HTMLElement | null {
  for (const sel of selectors ?? []) {
    for (const el of document.querySelectorAll<HTMLElement>(sel)) if (isVisible(el)) return el;
  }
  return null;
}

function useViewport() {
  const [vp, setVp] = useState(() => ({ w: window.innerWidth, h: window.innerHeight }));
  useEffect(() => {
    const on = () => setVp({ w: window.innerWidth, h: window.innerHeight });
    window.addEventListener("resize", on);
    return () => window.removeEventListener("resize", on);
  }, []);
  return vp;
}

/** True while a dialog that is not the tour's own is open: the tour steps aside until it closes. */
function useForeignDialog(): boolean {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const check = () =>
      setOpen(Boolean(document.querySelector("[role='dialog'][data-state='open']:not([data-tour-ui]), [role='alertdialog'][data-state='open']")));
    check();
    const mo = new MutationObserver(check);
    mo.observe(document.body, { subtree: true, childList: true, attributes: true, attributeFilter: ["data-state"] });
    return () => mo.disconnect();
  }, []);
  return open;
}

/**
 * Finds the step's control, waits for it while the page loads (up to TARGET_TIMEOUT_MS), finds it
 * again when the page re-renders it, and scrolls it into view the first time.
 */
function useTarget(step: TourStep, index: number, sheet: boolean) {
  const [el, setEl] = useState<HTMLElement | null>(null);
  const selectors = (sheet && step.sheetTarget) || step.target;
  const [settled, setSettled] = useState(!selectors);
  useEffect(() => {
    setEl(null);
    setSettled(!selectors);
    if (!selectors) return;
    const started = Date.now();
    let current: HTMLElement | null = null;
    let scrolled = false;
    const tick = () => {
      if (current && isVisible(current)) return;
      const found = findTarget(selectors);
      if (found) {
        current = found;
        setEl(found);
        setSettled(true);
        if (!scrolled) {
          scrolled = true;
          const r = found.getBoundingClientRect();
          const tall = r.height > window.innerHeight * 0.55;
          const inView = r.top >= 72 && r.bottom <= window.innerHeight * (sheet ? 0.5 : 1) - 8;
          if (!inView) {
            const prev = found.style.scrollMarginTop;
            found.style.scrollMarginTop = "84px";
            found.scrollIntoView({ block: sheet || tall ? "start" : "center", behavior: "smooth" });
            window.setTimeout(() => (found.style.scrollMarginTop = prev), 800);
          }
        }
        return;
      }
      if (current) {
        current = null;
        setEl(null);
      }
      if (Date.now() - started > TARGET_TIMEOUT_MS) setSettled(true);
    };
    tick();
    const t = window.setInterval(tick, 120);
    return () => window.clearInterval(t);
  }, [selectors, index, sheet]);
  return { el, settled };
}

/** "Do it for me" shows only while its control is there (no Start call during a call). */
function useCanDoIt(step: TourStep): boolean {
  const click = step.doIt?.click;
  const [can, setCan] = useState(Boolean(step.doIt) && !click);
  useEffect(() => {
    if (!step.doIt) return setCan(false);
    if (!click) return setCan(true);
    const check = () => setCan(Boolean(document.querySelector(click)));
    check();
    const t = window.setInterval(check, 250);
    return () => window.clearInterval(t);
  }, [step, click]);
  return can;
}

/** The control's box on screen, padded and clipped to the viewport, tracked every frame. */
function useHole(el: HTMLElement | null, vp: { w: number; h: number }): Box | null {
  const [box, setBox] = useState<Box | null>(null);
  useEffect(() => {
    if (!el) {
      setBox(null);
      return;
    }
    let raf = 0;
    let last = "";
    const frame = () => {
      const r = el.getBoundingClientRect();
      const top = Math.max(EDGE, r.top - PAD);
      const left = Math.max(EDGE, r.left - PAD);
      const bottom = Math.min(vp.h - EDGE, r.bottom + PAD);
      const right = Math.min(vp.w - EDGE, r.right + PAD);
      const next = bottom - top > 4 && right - left > 4 ? { top, left, width: right - left, height: bottom - top } : null;
      const key = next ? `${Math.round(top)},${Math.round(left)},${Math.round(next.width)},${Math.round(next.height)}` : "none";
      if (key !== last) {
        last = key;
        setBox(next);
      }
      raf = requestAnimationFrame(frame);
    };
    frame();
    return () => cancelAnimationFrame(raf);
  }, [el, vp.w, vp.h]);
  return box;
}

/** Popover position next to the hole: below, above, right, left, else the lower right corner. */
function place(hole: Box | null, w: number, h: number, vp: { w: number; h: number }): { x: number; y: number } {
  const clampX = (x: number) => Math.min(Math.max(x, EDGE), vp.w - w - EDGE);
  const clampY = (y: number) => Math.min(Math.max(y, EDGE), vp.h - h - EDGE);
  if (!hole) return { x: (vp.w - w) / 2, y: Math.max(EDGE, (vp.h - h) / 2 - vp.h * 0.06) };
  const cx = hole.left + hole.width / 2;
  const cy = hole.top + hole.height / 2;
  const bottom = hole.top + hole.height;
  const right = hole.left + hole.width;
  if (bottom + GAP + h <= vp.h - EDGE) return { x: clampX(cx - w / 2), y: bottom + GAP };
  if (hole.top - GAP - h >= EDGE) return { x: clampX(cx - w / 2), y: hole.top - GAP - h };
  if (right + GAP + w <= vp.w - EDGE) return { x: right + GAP, y: clampY(cy - h / 2) };
  if (hole.left - GAP - w >= EDGE) return { x: hole.left - GAP - w, y: clampY(cy - h / 2) };
  return { x: vp.w - w - EDGE * 2, y: vp.h - h - EDGE * 2 };
}

export function TourOverlay({
  step,
  index,
  agentId,
  progress,
  doing,
  onNext,
  onBack,
  onSkip,
  onPause,
  onFinish,
  onDoIt,
}: {
  step: TourStep;
  index: number;
  agentId: string | null;
  progress: StepProgress;
  doing: boolean;
  onNext: () => void;
  onBack: () => void;
  onSkip: () => void;
  onPause: () => void;
  onFinish: () => void;
  onDoIt: () => void;
}) {
  const vp = useViewport();
  const sheet = vp.w < SHEET_BELOW;
  const reduce = useReducedMotion() ?? false;
  const away = useForeignDialog();
  const { el, settled } = useTarget(step, index, sheet);
  const hole = useHole(el, vp);
  const pop = useRef<HTMLDivElement>(null);
  const title = useRef<HTMLHeadingElement>(null);
  const [size, setSize] = useState({ w: 360, h: 260 });
  const nudge = useAnimationControls();
  const isDone = step.id === "done";
  const visible = !away && settled;
  const canDoIt = useCanDoIt(step);

  useLayoutEffect(() => {
    const node = pop.current;
    if (!node) return;
    const measure = () => setSize({ w: node.offsetWidth, h: node.offsetHeight });
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(node);
    return () => ro.disconnect();
  }, [visible, index]);

  // Focus moves into the popover on every step, without scrolling the page.
  useEffect(() => {
    if (visible) title.current?.focus({ preventScroll: true });
  }, [visible, index]);

  // Esc pauses. Focus stays in the popover or the highlighted control (pointer users can use it).
  useEffect(() => {
    if (!visible) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !e.defaultPrevented) {
        e.preventDefault();
        onPause();
      }
    };
    const onFocus = (e: FocusEvent) => {
      const t = e.target as Node | null;
      if (
        !t ||
        pop.current?.contains(t) ||
        el?.contains(t) ||
        (t instanceof Element && t.closest("[data-tour-ui], [data-radix-popper-content-wrapper], [role='listbox']"))
      )
        return;
      title.current?.focus({ preventScroll: true });
    };
    window.addEventListener("keydown", onKey);
    document.addEventListener("focusin", onFocus);
    return () => {
      window.removeEventListener("keydown", onKey);
      document.removeEventListener("focusin", onFocus);
    };
  }, [visible, el, onPause]);

  const onPopKey = (e: ReactKeyboardEvent<HTMLDivElement>) => {
    if (e.key === "ArrowRight" && !isDone) {
      e.preventDefault();
      onNext();
    } else if (e.key === "ArrowLeft" && index > 0) {
      e.preventDefault();
      onBack();
    } else if (e.key === "Tab") {
      const items = [...(pop.current?.querySelectorAll<HTMLElement>("button:not([disabled]), a[href]") ?? [])];
      if (!items.length) return;
      const first = items[0]!;
      const last = items[items.length - 1]!;
      const active = document.activeElement;
      if (e.shiftKey && (active === first || active === title.current)) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && active === last) {
        e.preventDefault();
        first.focus();
      }
    }
  };

  const shake = () => {
    if (!reduce) void nudge.start({ x: [0, -6, 5, -3, 0], transition: { duration: 0.32 } });
  };

  const at = place(hole, size.w, size.h, vp);
  const spring = reduce ? { duration: 0 } : { type: "spring" as const, stiffness: 260, damping: 32, mass: 0.9 };
  const blockers: Box[] = hole
    ? [
        { top: 0, left: 0, width: vp.w, height: hole.top },
        { top: hole.top + hole.height, left: 0, width: vp.w, height: Math.max(0, vp.h - hole.top - hole.height) },
        { top: hole.top, left: 0, width: hole.left, height: hole.height },
        { top: hole.top, left: hole.left + hole.width, width: Math.max(0, vp.w - hole.left - hole.width), height: hole.height },
      ]
    : [{ top: 0, left: 0, width: vp.w, height: vp.h }];
  const spot = hole ?? { top: vp.h / 2, left: vp.w / 2, width: 0, height: 0 };

  return createPortal(
    <AnimatePresence>
      {!away && (
        <motion.div
          key="tour-layer"
          data-tour-ui
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: reduce ? 0 : 0.22 }}
        >
          {/* The dim with a cut-out: one shadow around the hole, gliding from control to control. */}
          <motion.div
            aria-hidden
            className="pointer-events-none fixed left-0 top-0 z-[55] rounded-panel"
            style={{ boxShadow: "0 0 0 200vmax var(--overlay)" }}
            initial={false}
            animate={{ x: spot.left, y: spot.top, width: spot.width, height: spot.height }}
            transition={spring}
          >
            {hole && (
              <>
                <span className="absolute -inset-[3px] rounded-[15px]" style={{ boxShadow: "0 0 0 6px var(--halo-soft)" }} />
                <span className="tour-ring absolute -inset-[3px] rounded-[15px] grad-heat p-[2px]" />
                {!reduce && (
                  <motion.span
                    className="absolute -inset-[9px] rounded-[18px] border-2 border-[var(--halo)]"
                    animate={{ opacity: [0, 0.75, 0], scale: [0.99, 1, 1.012] }}
                    transition={{ duration: 1.8, repeat: Infinity, ease: "easeOut" }}
                  />
                )}
              </>
            )}
          </motion.div>
          {/* Clicks outside the highlighted control stay with the tour. */}
          {blockers.map((b, i) => (
            <div key={i} aria-hidden className="fixed z-[55]" style={b} onPointerDown={shake} />
          ))}

          {visible && (
            <motion.div
              ref={pop}
              role="dialog"
              aria-modal="false"
              aria-labelledby="tour-title"
              aria-describedby="tour-body"
              data-tour-ui
              onKeyDown={onPopKey}
              className={cn(
                "fixed z-[57] flex flex-col border border-line bg-surface shadow-pop",
                sheet
                  ? "inset-x-0 bottom-0 max-h-[62dvh] overflow-y-auto rounded-t-[20px] pb-[env(safe-area-inset-bottom)]"
                  : cn("left-0 top-0 rounded-panel", isDone ? "w-[420px]" : "w-[360px]"),
              )}
              initial={sheet ? { y: "100%" } : { opacity: 0, scale: 0.96, x: at.x, y: at.y + 6 }}
              animate={sheet ? { y: 0 } : { opacity: 1, scale: 1, x: at.x, y: at.y }}
              transition={sheet ? (reduce ? { duration: 0 } : { duration: 0.32, ease: EASE_OUT_SOFT }) : spring}
            >
              <motion.div animate={nudge}>
                {isDone ? (
                  <Recap agentId={agentId} titleRef={title} onFinish={onFinish} reduce={reduce} />
                ) : (
                  <StepCard
                    step={step}
                    index={index}
                    progress={progress}
                    doing={doing}
                    canDoIt={canDoIt}
                    titleRef={title}
                    onNext={onNext}
                    onBack={onBack}
                    onSkip={onSkip}
                    onPause={onPause}
                    onDoIt={onDoIt}
                    reduce={reduce}
                  />
                )}
              </motion.div>
            </motion.div>
          )}
        </motion.div>
      )}
    </AnimatePresence>,
    document.body,
  );
}

function Segments({ index, reduce }: { index: number; reduce: boolean }) {
  return (
    <div aria-hidden className="flex gap-1">
      {Array.from({ length: COUNTED }, (_, i) => (
        <span key={i} className="relative h-1 flex-1 overflow-hidden rounded-full bg-surface-3">
          {i < index && <span className="absolute inset-0 rounded-full bg-accent/60" />}
          {i === index && (
            <motion.span
              className="absolute inset-0 origin-left rounded-full grad-action"
              initial={reduce ? false : { scaleX: 0 }}
              animate={{ scaleX: 1 }}
              transition={{ duration: 0.5, ease: EASE_OUT_SOFT }}
            />
          )}
        </span>
      ))}
    </div>
  );
}

function StepCard({
  step,
  index,
  progress,
  doing,
  canDoIt,
  titleRef,
  onNext,
  onBack,
  onSkip,
  onPause,
  onDoIt,
  reduce,
}: {
  step: TourStep;
  index: number;
  progress: StepProgress;
  doing: boolean;
  canDoIt: boolean;
  titleRef: RefObject<HTMLHeadingElement | null>;
  onNext: () => void;
  onBack: () => void;
  onSkip: () => void;
  onPause: () => void;
  onDoIt: () => void;
  reduce: boolean;
}) {
  const Icon = step.icon;
  return (
    <>
      <div className="flex items-center gap-3 px-4 pt-4">
        <motion.span
          key={step.id}
          className="grid size-9 shrink-0 place-items-center rounded-full grad-action text-white shadow-[0_6px_14px_-8px_rgb(51_70_232/0.8)]"
          initial={reduce ? false : { scale: 0.7, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={{ duration: 0.36, ease: EASE_OUT_SOFT }}
        >
          <Icon className="size-[18px]" strokeWidth={1.75} aria-hidden />
        </motion.span>
        <p className="min-w-0 flex-1 text-[12.5px] text-fg-3">
          Step <span className="font-medium text-fg tnum">{index + 1}</span> of <span className="tnum">{COUNTED}</span>
        </p>
        <Button variant="ghost" size="sm" className="-mr-1" onClick={onSkip}>
          Skip tour
        </Button>
        <IconButton label="Pause the tour (Esc)" className="-mr-2 size-8" onClick={onPause}>
          <Pause className="size-4" aria-hidden />
        </IconButton>
      </div>
      <div className="px-4 pt-3">
        <Segments index={index} reduce={reduce} />
      </div>
      <div className="px-4 pt-4">
        <h2
          id="tour-title"
          ref={titleRef}
          tabIndex={-1}
          className="font-display text-[17px] font-medium leading-snug tracking-[-0.01em] text-fg outline-none"
        >
          {step.title}
        </h2>
        <p id="tour-body" className="mt-1.5 text-[13.5px] leading-relaxed text-fg-2">
          {step.body}
        </p>
        <AnimatePresence initial={false} mode="wait">
          {progress.done ? (
            <motion.p
              key="done"
              className="mt-3 flex items-center gap-2 text-[12.5px] font-medium text-success-text"
              initial={{ opacity: 0, y: 3 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
            >
              <span className="grid size-4 place-items-center rounded-full bg-success-soft">
                <Check className="size-3" strokeWidth={3} aria-hidden />
              </span>
              Done
            </motion.p>
          ) : progress.waiting && step.waitingFor ? (
            <motion.p
              key="waiting"
              className="mt-3 flex items-center gap-2 text-[12.5px] text-accent-text"
              initial={{ opacity: 0, y: 3 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
            >
              <span className="relative grid size-4 place-items-center" aria-hidden>
                {!reduce && <span className="absolute inset-0 animate-ping rounded-full bg-accent/30" />}
                <span className="size-2 rounded-full bg-accent" />
              </span>
              {step.waitingFor}, or press Next.
            </motion.p>
          ) : null}
        </AnimatePresence>
      </div>
      <div className="mt-4 flex items-center gap-2 border-t border-line px-4 py-3">
        {index > 0 && (
          <Button variant="ghost" size="sm" className="-ml-2" icon={<ChevronLeft aria-hidden />} onClick={onBack}>
            Back
          </Button>
        )}
        <span className="flex-1" />
        {step.doIt && canDoIt && !progress.done && (
          <Button variant="secondary" size="sm" icon={<Wand2 aria-hidden />} pending={doing} onClick={onDoIt}>
            {step.doIt.label}
          </Button>
        )}
        <Button variant="primary" size="sm" onClick={onNext}>
          Next
        </Button>
      </div>
    </>
  );
}

const RECAP = [
  {
    key: "agent",
    label: "Open your agent",
    hint: "Prompt, voice and price",
    icon: Bot,
    to: (id: string | null) => (id ? `/agents/${id}/edit` : "/agents"),
  },
  {
    key: "test",
    label: "Call it again",
    hint: "Browser test call",
    icon: PhoneCall,
    to: (id: string | null) => (id ? `/agents/${id}/testing` : "/agents"),
  },
  { key: "number", label: "Connect a number", hint: "SIP trunk or WhatsApp", icon: PhoneForwarded, to: () => "/phone-numbers" },
  { key: "review", label: "Review calls", hint: "Labels and quality checks", icon: ListChecks, to: () => "/review" },
];

function Recap({
  agentId,
  titleRef,
  onFinish,
  reduce,
}: {
  agentId: string | null;
  titleRef: RefObject<HTMLHeadingElement | null>;
  onFinish: () => void;
  reduce: boolean;
}) {
  const step = STEPS[STEPS.length - 1]!;
  return (
    <>
      <div className="relative overflow-hidden px-5 pb-4 pt-6 sm:rounded-t-panel">
        <div aria-hidden className="glow-backdrop pointer-events-none absolute inset-0 opacity-70" />
        <div className="relative flex flex-col items-start gap-4">
          <span className="relative grid size-12 place-items-center">
            {!reduce && (
              <motion.span
                aria-hidden
                className="absolute inset-0 rounded-full bg-[var(--halo-soft)]"
                initial={{ scale: 0.6, opacity: 0 }}
                animate={{ scale: [0.6, 1.5], opacity: [0.9, 0] }}
                transition={{ duration: 1.1, ease: "easeOut", delay: 0.15 }}
              />
            )}
            <motion.span
              className="relative grid size-12 place-items-center rounded-full grad-action text-white shadow-[0_10px_24px_-10px_rgb(51_70_232/0.85)]"
              initial={reduce ? false : { scale: 0.6, rotate: -12, opacity: 0 }}
              animate={{ scale: 1, rotate: 0, opacity: 1 }}
              transition={{ type: "spring", stiffness: 320, damping: 18 }}
            >
              <Check className="size-6" strokeWidth={2.5} aria-hidden />
            </motion.span>
          </span>
          <div>
            <h2
              id="tour-title"
              ref={titleRef}
              tabIndex={-1}
              className="font-display text-[20px] font-medium leading-snug tracking-[-0.015em] text-fg outline-none"
            >
              {step.title}
            </h2>
            <p id="tour-body" className="mt-1.5 text-[13.5px] leading-relaxed text-fg-2">
              {step.body}
            </p>
          </div>
        </div>
      </div>
      <ul className="grid grid-cols-[minmax(0,1fr)] gap-1 px-3 sm:grid-cols-2">
        {RECAP.map((r, i) => {
          const Icon = r.icon;
          return (
            <motion.li
              key={r.key}
              initial={reduce ? false : { opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.26, delay: 0.2 + i * 0.05, ease: EASE_OUT_SOFT }}
            >
              <Link
                to={r.to(agentId)}
                onClick={onFinish}
                className={cn(
                  "group flex items-center gap-3 rounded-control px-2 py-2.5 transition-colors duration-150 hover:bg-accent-soft/50",
                  focusRing,
                )}
              >
                <span className="grid size-8 shrink-0 place-items-center rounded-control bg-accent-soft text-accent-text transition-transform duration-200 group-hover:scale-105">
                  <Icon className="size-4" strokeWidth={1.75} aria-hidden />
                </span>
                <span className="flex min-w-0 flex-col">
                  <span className="text-[13px] font-medium text-fg">{r.label}</span>
                  <span className="text-[12px] text-fg-3">{r.hint}</span>
                </span>
              </Link>
            </motion.li>
          );
        })}
      </ul>
      <div className="mt-3 flex items-center gap-3 border-t border-line px-5 py-3.5">
        <p className="min-w-0 flex-1 text-[12.5px] text-fg-3">Guided setup stays in your account menu.</p>
        <Button variant="primary" size="sm" onClick={onFinish}>
          Finish
        </Button>
      </div>
    </>
  );
}
