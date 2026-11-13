import { GripVertical } from "lucide-react";
import { animate, motion, useDragControls, useMotionValue } from "motion/react";
import { useEffect, useRef, type KeyboardEvent } from "react";
import { cn, focusRing } from "../../components";
import { VoiceCopilot } from "../copilot/VoiceCopilot";
import { AskPanel } from "./AskPanel";
import { agentFlowPath } from "../../lib/paths";

/** Full-height editors where a floating dock would sit on the canvas: the dock moves into the top bar. */
export function isFullHeightEditor(pathname: string): boolean {
  const path = pathname.replace(/\/$/, "");
  return path === agentFlowPath(path.split("/")[2] ?? "");
}

const POSITION_KEY = "cw.dock.offset";
const NUDGE_PX = 24;
/** Gap between the dock and the window edge, matching its bottom-4 right-4 home. */
const GAP = 16;

const reducedMotion = () => typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

type Side = "left" | "right" | "top" | "bottom";
const SIDES: readonly Side[] = ["right", "bottom", "left", "top"];

interface Position {
  x: number;
  y: number;
  side: Side;
}

function savedPosition(): Position {
  try {
    const v = JSON.parse(localStorage.getItem(POSITION_KEY) ?? "null") as Partial<Position> | null;
    if (v && typeof v.x === "number" && typeof v.y === "number") {
      return { x: v.x, y: v.y, side: SIDES.includes(v.side as Side) ? (v.side as Side) : "right" };
    }
  } catch {
    // Storage blocked or malformed: start in the corner.
  }
  return { x: 0, y: 0, side: "right" };
}

function savePosition(p: Position) {
  try {
    localStorage.setItem(POSITION_KEY, JSON.stringify({ x: Math.round(p.x), y: Math.round(p.y), side: p.side }));
  } catch {
    // Not remembered this time; the dock still moves.
  }
}

/** The window edge a box is closest to. */
export function nearestSide(r: { left: number; right: number; top: number; bottom: number }, width: number, height: number): Side {
  const d: Record<Side, number> = { right: width - r.right, bottom: height - r.bottom, left: r.left, top: r.top };
  return SIDES.reduce((a, b) => (d[b] < d[a] ? b : a));
}

/**
 * Offsets (from the bottom-right home) that put a w-by-h dock flush on `side`, keeping its place
 * along that edge but inside the window.
 */
export function pinnedOffset(side: Side, x: number, y: number, w: number, h: number, width: number, height: number): { x: number; y: number } {
  const minX = Math.min(0, -(width - 2 * GAP - w));
  const minY = Math.min(0, -(height - 2 * GAP - h));
  const clamp = (v: number, min: number) => Math.min(0, Math.max(min, v));
  if (side === "right") return { x: 0, y: clamp(y, minY) };
  if (side === "left") return { x: minX, y: clamp(y, minY) };
  if (side === "bottom") return { x: clamp(x, minX), y: 0 };
  return { x: clamp(x, minX), y: minY };
}

/**
 * The shell's assistant controls (spec 006): type a command, talk to the voice copilot and "Ask
 * about your data", in one compact capsule. `dock` floats at the bottom right; drag it by its grip
 * and it settles on the nearest window edge, so it never floats over the middle of a page. The
 * arrow keys slide it along its edge, or across to the edge they point at. Its edge and place are
 * remembered per browser; double-click the grip to put it back. `bar` sits in the top bar on
 * full-height editors. Neither requests a credential until it is used (FR-020).
 */
export function CopilotDock({ placement = "dock" }: { placement?: "dock" | "bar" }) {
  const bar = placement === "bar";
  const bounds = useRef<HTMLDivElement>(null);
  const dock = useRef<HTMLDivElement>(null);
  const controls = useDragControls();
  const start = useRef(savedPosition());
  const side = useRef<Side>(start.current.side);
  const x = useMotionValue(bar ? 0 : start.current.x);
  const y = useMotionValue(bar ? 0 : start.current.y);

  /** Put the dock flush on `to` (default: its current edge), sliding there unless `instant`. */
  const pin = (to: Side = side.current, along?: { x: number; y: number }, instant = false) => {
    const el = dock.current;
    if (!el) return;
    side.current = to;
    const t = pinnedOffset(to, along?.x ?? x.get(), along?.y ?? y.get(), el.offsetWidth, el.offsetHeight, window.innerWidth, window.innerHeight);
    if (instant || reducedMotion()) {
      x.set(t.x);
      y.set(t.y);
    } else {
      const spring = { type: "spring", stiffness: 520, damping: 42 } as const;
      void animate(x, t.x, spring);
      void animate(y, t.y, spring);
    }
    savePosition({ ...t, side: to });
  };

  // Stay on the remembered edge, inside the window, as it resizes.
  useEffect(() => {
    if (bar) return;
    const keep = () => pin(side.current, undefined, true);
    keep();
    window.addEventListener("resize", keep);
    return () => window.removeEventListener("resize", keep);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- pin reads only refs and motion values
  }, [bar]);

  const settle = () => {
    const el = dock.current;
    if (!el) return;
    pin(nearestSide(el.getBoundingClientRect(), window.innerWidth, window.innerHeight));
  };

  const nudge = (e: KeyboardEvent) => {
    const moves: Record<string, { to: Side; dx: number; dy: number }> = {
      ArrowLeft: { to: "left", dx: -NUDGE_PX, dy: 0 },
      ArrowRight: { to: "right", dx: NUDGE_PX, dy: 0 },
      ArrowUp: { to: "top", dx: 0, dy: -NUDGE_PX },
      ArrowDown: { to: "bottom", dx: 0, dy: NUDGE_PX },
    };
    const m = moves[e.key];
    if (!m) return;
    e.preventDefault();
    const vertical = side.current === "left" || side.current === "right";
    const along = vertical ? m.dy !== 0 : m.dx !== 0;
    // Along the edge: slide. Across it: move to the edge the arrow points at.
    if (along) pin(side.current, { x: x.get() + m.dx, y: y.get() + m.dy }, true);
    else pin(m.to);
  };

  const reset = () => pin("right", { x: 0, y: 0 });

  return (
    <>
      {!bar && <div ref={bounds} aria-hidden className="pointer-events-none fixed inset-4 z-0" />}
      <motion.div
        ref={dock}
        role="region"
        aria-label="Assistant"
        drag={!bar}
        dragControls={controls}
        dragListener={false}
        dragConstraints={bounds}
        dragElastic={0}
        dragMomentum={false}
        onDragEnd={settle}
        style={bar ? undefined : { x, y }}
        initial={{ opacity: 0, scale: 0.97 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.28, ease: [0.16, 1, 0.3, 1] }}
        className={cn(
          "flex items-center gap-0.5 rounded-full border border-line",
          bar ? "relative bg-surface p-0.5" : "fixed bottom-4 right-4 z-40 bg-surface/90 p-1 shadow-pop backdrop-blur-md",
        )}
      >
        {!bar && (
          <button
            type="button"
            aria-label="Move the assistant along the window edges. Drag, or use the arrow keys. Double-click to put it back."
            title="Drag to another edge. Double-click to put it back."
            onPointerDown={(e) => controls.start(e)}
            onKeyDown={nudge}
            onDoubleClick={reset}
            className={cn(
              "grid h-9 w-5 cursor-grab touch-none place-items-center rounded-full text-fg-3 hover:text-fg-2 active:cursor-grabbing",
              focusRing,
            )}
          >
            <GripVertical className="size-4" aria-hidden />
          </button>
        )}
        <VoiceCopilot placement={placement} spaceToTalk={!bar} />
        <span aria-hidden className="mx-1 h-5 w-px bg-line" />
        <AskPanel placement={placement} />
      </motion.div>
    </>
  );
}
