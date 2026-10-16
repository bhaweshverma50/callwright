import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import type { CSSProperties, ReactNode } from "react";
import { cn } from "./cn";
import { EASE_OUT_SOFT, STATE_DURATION } from "./motion";

export interface FlowNode {
  key: string;
  label: string;
  icon: ReactNode;
  /** Extra lines under the label (model, rate). */
  detail?: ReactNode;
  /** Muted, dashed circle: an optional link that is switched off. */
  off?: boolean;
}

export interface FlowChainProps {
  nodes: FlowNode[];
  /** The node shown as the gradient disc with a halo. */
  active?: string | null;
  /** Dashes flow along every connector, in sync. Static under reduced motion. */
  flow?: boolean;
  size?: "sm" | "md" | "lg";
  onConsole?: boolean;
  /**
   * "narrow" turns the chain vertical below 34rem of container width, "tight" below 20rem (short
   * chains), "never" keeps it in a row, "always" keeps it vertical (rows with a value on the right).
   */
  stack?: "narrow" | "tight" | "never" | "always";
  /** Hide node labels visually (still read by screen readers), for tight spaces. */
  hideLabels?: boolean;
  /** Text centred on each connector (length nodes - 1), for example a running subtotal. */
  linkLabels?: (ReactNode | null)[];
  /**
   * Wraps a node (circle and labels) in an interactive element, for example a popover trigger.
   * The returned element must carry the `flow-node-body` class so it lays out like a plain node.
   */
  renderNode?: (node: FlowNode, content: ReactNode, index: number) => ReactNode;
  /** Minimum row height in the vertical layout. */
  rowHeight?: number;
  label?: string;
  className?: string;
}

const SIZES = { sm: 28, md: 36, lg: 44 } as const;

/**
 * The one component for every horizontal flow (signal chain, build loop). Equal grid columns put
 * each circle on the same pitch whatever its label length; connectors are a single layer drawn
 * from circle edge to circle edge with the same gap, so all segments are the same length and sit
 * on the centre line (geometry in index.css, `.flow`). Labels wrap to two lines under the circle.
 */
export function FlowChain({
  nodes,
  active,
  flow = false,
  size = "md",
  onConsole,
  stack = "narrow",
  hideLabels,
  linkLabels,
  renderNode,
  rowHeight,
  label = "Signal chain",
  className,
}: FlowChainProps) {
  const reduce = useReducedMotion();
  const d = SIZES[size];
  const style = {
    "--n": nodes.length,
    "--r": `${d / 2}px`,
    "--seg-base": onConsole ? "var(--console-line)" : "var(--border-strong)",
    ...(rowHeight ? { "--row": `${rowHeight}px` } : {}),
  } as CSSProperties;

  return (
    <div className={cn("flow", className)} data-stack={stack} data-flow={flow && !reduce ? "true" : "false"} style={style}>
      <ol aria-label={label} className="flow-grid">
        {nodes.slice(0, -1).map((n, i) => (
          <li key={`seg-${n.key}`} aria-hidden className="contents">
            <span className="flow-seg" style={{ "--i": i } as CSSProperties}>
              <i />
            </span>
            {linkLabels?.[i] != null && (
              <span
                className={cn("flow-seg-label z-[2] font-mono text-[11.5px] tnum", onConsole ? "text-console-fg-2" : "text-fg-3")}
                style={{ "--i": i } as CSSProperties}
              >
                {linkLabels[i]}
              </span>
            )}
          </li>
        ))}
        {nodes.map((n, i) => {
          const on = active === n.key;
          const content = (
            <>
              <span
                className={cn(
                  "relative grid shrink-0 place-items-center rounded-full border transition-[background-color,border-color,color] duration-[var(--state-duration)] ease-[var(--ease-out-soft)]",
                  size === "sm" ? "[&_svg]:size-3.5" : size === "md" ? "[&_svg]:size-4" : "[&_svg]:size-5",
                  on
                    ? onConsole
                      ? "border-transparent bg-console-2 text-white"
                      : "border-transparent bg-surface text-white"
                    : n.off
                      ? onConsole
                        ? "border-dashed border-console-line bg-console text-console-fg-2"
                        : "border-dashed border-line-strong bg-surface text-fg-3"
                      : onConsole
                        ? "border-console-line bg-console-2 text-console-fg-2"
                        : "border-line-strong bg-surface text-accent-text",
                )}
                style={{ width: d, height: d }}
                data-flow-disc=""
                aria-current={on ? "step" : undefined}
              >
                <ActiveDisc on={on} />
                <span className="relative grid place-items-center">{n.icon}</span>
              </span>
              <span className={cn("flex min-w-0 max-w-full flex-col gap-0.5", hideLabels && "sr-only")}>
                <span
                  className={cn(
                    "line-clamp-2 text-[12px] leading-tight",
                    onConsole ? (on ? "text-console-fg" : "text-console-fg-2") : on ? "font-medium text-fg" : "text-fg-2",
                  )}
                >
                  {n.label}
                </span>
                {n.detail}
              </span>
            </>
          );
          return (
            <li key={n.key} className="flow-node">
              {renderNode ? renderNode(n, content, i) : <div className="flow-node-body">{content}</div>}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

/**
 * The active state of a disc (chain node or step): the halo behind, then the gradient fill. Both
 * come in together from 0.85 of the disc's size over --state-duration and leave the same way, so
 * activation never snaps. Render it as the disc's first children, before the disc's content
 * (wrapped in a positioned element so it paints above the fill).
 */
export function ActiveDisc({ on }: { on: boolean }) {
  return (
    <>
      <Halo on={on} />
      <span aria-hidden className="disc-fill grad-action" data-on={on} />
    </>
  );
}

/**
 * Soft halo around an active disc: a steady ring plus a pulse that grows out of the disc's own edge
 * (index.css `.halo`). It fades and scales in on activation and out on deactivation; under reduced
 * motion only the steady ring shows.
 */
export function Halo({ on }: { on: boolean }) {
  return (
    <AnimatePresence initial={false}>
      {on && (
        <motion.span
          key="halo"
          aria-hidden
          className="halo"
          initial={{ opacity: 0, scale: 0.85 }}
          animate={{ opacity: 1, scale: 1 }}
          exit={{ opacity: 0, scale: 0.85 }}
          transition={{ duration: STATE_DURATION, ease: EASE_OUT_SOFT }}
        >
          <i className="halo-ring" />
          <i className="halo-pulse" />
        </motion.span>
      )}
    </AnimatePresence>
  );
}
