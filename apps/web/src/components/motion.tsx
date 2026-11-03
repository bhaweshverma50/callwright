/**
 * Motion helpers (docs/DESIGN.md section 8). Everything animates transform and opacity only, and
 * every helper respects prefers-reduced-motion through `useReducedMotion` or the app-wide
 * `MotionConfig reducedMotion="user"`.
 */
import { animate, motion, useReducedMotion, type Variants } from "motion/react";
import { useCallback, useEffect, useRef, useState, type PointerEvent, type ReactNode } from "react";
import { cn } from "./cn";

export const EASE_OUT = [0.16, 1, 0.3, 1] as const;
/** `--ease-out-soft` in index.css. */
export const EASE_OUT_SOFT = [0.22, 1, 0.36, 1] as const;
/** `--state-duration` in index.css, in seconds: a node or step becoming active, and leaving it. */
export const STATE_DURATION = 0.36;

/** Fade and 6px rise for routed pages. Keyed by the caller so each route animates in. */
export function PageTransition({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <motion.div className={className} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.22, ease: EASE_OUT }}>
      {children}
    </motion.div>
  );
}

const staggerParent: Variants = {
  hidden: {},
  show: { transition: { staggerChildren: 0.04, delayChildren: 0.02 } },
};
const staggerChild: Variants = {
  hidden: { opacity: 0, y: 8 },
  show: { opacity: 1, y: 0, transition: { duration: 0.26, ease: EASE_OUT } },
};

/** Staggered first-load reveal: wrap blocks in `Reveal`, each block in `RevealItem`. */
export function Reveal({ children, className, as = "div" }: { children: ReactNode; className?: string; as?: "div" | "ol" | "ul" | "section" }) {
  const M = motion[as];
  return (
    <M className={className} variants={staggerParent} initial="hidden" animate="show">
      {children}
    </M>
  );
}

export function RevealItem({
  children,
  className,
  as = "div",
}: {
  children?: ReactNode;
  className?: string;
  as?: "div" | "li" | "section" | "article";
}) {
  const M = motion[as];
  return (
    <M className={className} variants={staggerChild}>
      {children}
    </M>
  );
}

/**
 * Animated number: springs from the previous value to the new one. The final frame is always the
 * exact `format(value)` string, so screen readers and tests read the precise figure.
 */
export function useTicker(value: number, { fromZero = false, duration = 0.7 }: { fromZero?: boolean; duration?: number } = {}) {
  const reduce = useReducedMotion();
  const [shown, setShown] = useState(fromZero && !reduce ? 0 : value);
  const prev = useRef(fromZero && !reduce ? 0 : value);
  useEffect(() => {
    if (reduce || prev.current === value) {
      prev.current = value;
      setShown(value);
      return;
    }
    const controls = animate(prev.current, value, { duration, ease: EASE_OUT, onUpdate: setShown });
    prev.current = value;
    return () => controls.stop();
  }, [value, reduce, duration]);
  return { shown, done: shown === value };
}

export function Ticker({
  value,
  format,
  className,
  fromZero,
}: {
  value: number;
  format: (n: number) => string;
  className?: string;
  fromZero?: boolean;
}) {
  const { shown } = useTicker(value, { fromZero });
  return <span className={cn("tnum", className)}>{format(shown)}</span>;
}

interface RippleDot {
  id: number;
  x: number;
  y: number;
  size: number;
}

/** Ripple from the pointer on press. Returns the handler and the nodes to render inside. */
export function useRipple() {
  const reduce = useReducedMotion();
  const [dots, setDots] = useState<RippleDot[]>([]);
  const seq = useRef(0);
  const timers = useRef(new Set<ReturnType<typeof setTimeout>>());
  // A ripple outliving its button (unmounted mid-animation) must not set state afterwards.
  useEffect(() => {
    const pending = timers.current;
    return () => {
      for (const t of pending) clearTimeout(t);
      pending.clear();
    };
  }, []);
  const onPointerDown = useCallback(
    (e: PointerEvent<HTMLElement>) => {
      if (reduce) return;
      const r = e.currentTarget.getBoundingClientRect();
      const size = Math.max(r.width, r.height) * 2.2;
      const id = ++seq.current;
      setDots((d) => [...d, { id, x: e.clientX - r.left, y: e.clientY - r.top, size }]);
      const t = setTimeout(() => {
        timers.current.delete(t);
        setDots((d) => d.filter((x) => x.id !== id));
      }, 500);
      timers.current.add(t);
    },
    [reduce],
  );
  const ripples = dots.map((d) => <span key={d.id} aria-hidden className="ripple" style={{ left: d.x, top: d.y, width: d.size, height: d.size }} />);
  return { onPointerDown, ripples };
}
