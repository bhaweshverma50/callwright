import { GripVertical } from "lucide-react";
import { motion, useDragControls, useMotionValue } from "motion/react";
import { useEffect, useRef, type KeyboardEvent } from "react";
import { cn, focusRing } from "../../components";
import { VoiceCopilot } from "../copilot/VoiceCopilot";
import { AskPanel } from "./AskPanel";

/** Full-height editors where a floating dock would sit on the canvas: the dock moves into the top bar. */
export function isFullHeightEditor(pathname: string): boolean {
  return /^\/agents\/[^/]+\/flow\/?$/.test(pathname);
}

const POSITION_KEY = "cw.dock.offset";
const NUDGE_PX = 24;

function savedOffset(): { x: number; y: number } {
  try {
    const v = JSON.parse(localStorage.getItem(POSITION_KEY) ?? "null") as { x?: unknown; y?: unknown } | null;
    if (v && typeof v.x === "number" && typeof v.y === "number") return { x: v.x, y: v.y };
  } catch {
    // Storage blocked or malformed: start in the corner.
  }
  return { x: 0, y: 0 };
}

function saveOffset(x: number, y: number) {
  try {
    localStorage.setItem(POSITION_KEY, JSON.stringify({ x: Math.round(x), y: Math.round(y) }));
  } catch {
    // Not remembered this time; the dock still moves.
  }
}

/**
 * The shell's assistant controls (spec 006): type a command, talk to the voice copilot and "Ask
 * about your data", in one compact capsule. `dock` floats at the bottom right and can be dragged
 * by its grip (or nudged with the arrow keys) anywhere in the window, remembered per browser, so it
 * never has to cover a page's own buttons; double-click the grip to put it back. `bar` sits in the
 * top bar on full-height editors. Neither requests a credential until it is used (FR-020).
 */
export function CopilotDock({ placement = "dock" }: { placement?: "dock" | "bar" }) {
  const bar = placement === "bar";
  const bounds = useRef<HTMLDivElement>(null);
  const controls = useDragControls();
  const start = useRef(savedOffset());
  const x = useMotionValue(bar ? 0 : start.current.x);
  const y = useMotionValue(bar ? 0 : start.current.y);

  // Keep a remembered position on screen after the window shrinks.
  useEffect(() => {
    if (bar) return;
    const clamp = () => {
      const maxLeft = -(window.innerWidth - 240);
      const maxUp = -(window.innerHeight - 80);
      x.set(Math.min(0, Math.max(maxLeft, x.get())));
      y.set(Math.min(0, Math.max(maxUp, y.get())));
    };
    clamp();
    window.addEventListener("resize", clamp);
    return () => window.removeEventListener("resize", clamp);
  }, [bar, x, y]);

  const nudge = (e: KeyboardEvent) => {
    const moves: Record<string, [number, number]> = {
      ArrowLeft: [-NUDGE_PX, 0],
      ArrowRight: [NUDGE_PX, 0],
      ArrowUp: [0, -NUDGE_PX],
      ArrowDown: [0, NUDGE_PX],
    };
    const m = moves[e.key];
    if (!m) return;
    e.preventDefault();
    const nx = Math.min(0, Math.max(-(window.innerWidth - 240), x.get() + m[0]));
    const ny = Math.min(0, Math.max(-(window.innerHeight - 80), y.get() + m[1]));
    x.set(nx);
    y.set(ny);
    saveOffset(nx, ny);
  };

  const reset = () => {
    x.set(0);
    y.set(0);
    saveOffset(0, 0);
  };

  return (
    <>
      {!bar && <div ref={bounds} aria-hidden className="pointer-events-none fixed inset-4 z-0" />}
      <motion.div
        role="region"
        aria-label="Assistant"
        drag={!bar}
        dragControls={controls}
        dragListener={false}
        dragConstraints={bounds}
        dragElastic={0}
        dragMomentum={false}
        onDragEnd={() => saveOffset(x.get(), y.get())}
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
            aria-label="Move the assistant. Drag, or use the arrow keys. Double-click to put it back."
            title="Drag to move. Double-click to put it back."
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
