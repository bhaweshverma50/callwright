import * as RTT from "@radix-ui/react-tooltip";
import { useState, type FocusEvent, type ReactElement, type ReactNode } from "react";
import { cn } from "./cn";

/**
 * Tooltip timing (docs/DESIGN.md section 8): about 300 ms before the first tip opens, then any
 * adjacent tip opens at once while the pointer moves between triggers within the skip window.
 */
export const TOOLTIP_DELAY_MS = 300;
export const TOOLTIP_SKIP_DELAY_MS = 400;

export function TooltipProvider({ children }: { children: ReactNode }) {
  return (
    <RTT.Provider delayDuration={TOOLTIP_DELAY_MS} skipDelayDuration={TOOLTIP_SKIP_DELAY_MS}>
      {children}
    </RTT.Provider>
  );
}

/**
 * Focus opens a tip only when it is keyboard focus. A click, or focus moved by code after a click
 * (an inspector's autofocused close button), would otherwise pop a tip nobody asked for.
 */
function keyboardFocusOnly(e: FocusEvent<HTMLElement>) {
  try {
    if (!e.currentTarget.matches(":focus-visible")) e.preventDefault();
  } catch {
    /* :focus-visible unsupported: open on any focus */
  }
}

export interface TooltipProps {
  content: ReactNode;
  children: ReactElement;
  side?: "top" | "right" | "bottom" | "left";
  align?: "start" | "center" | "end";
  /** When false the tooltip never opens (for example nav labels while the sidebar is expanded). */
  enabled?: boolean;
}

/**
 * Short label on hover and keyboard focus. One style everywhere: a small ink card with an arrow, a
 * readable max width, kept 8px inside the viewport, fading and settling in from its trigger. Never
 * the only place important text lives.
 *
 * The trigger is always wrapped (even while disabled) so toggling `enabled` never remounts the
 * child, which would drop refs and observers attached to it.
 */
export function Tooltip({ content, children, side = "top", align = "center", enabled = true }: TooltipProps) {
  const [open, setOpen] = useState(false);
  // While disabled Radix sees the tip as closed, so it never reports the pointer leaving. Recording
  // a hover then would leave `open` stuck, and every tip hovered while disabled would pop up together
  // once enabled (all the nav labels when the sidebar collapses). So: no opens while disabled, and
  // drop any open state the moment it becomes disabled.
  if (!enabled && open) setOpen(false);
  return (
    <RTT.Root open={enabled && open} onOpenChange={(o) => setOpen(enabled && o)}>
      <RTT.Trigger asChild onFocus={keyboardFocusOnly}>
        {children}
      </RTT.Trigger>
      <RTT.Portal>
        <RTT.Content
          side={side}
          align={align}
          sideOffset={6}
          collisionPadding={8}
          className={cn(
            "tooltip z-[70] max-w-[min(18rem,var(--radix-tooltip-content-available-width))] rounded-control px-2.5 py-1.5",
            "text-[12px] font-medium leading-snug [overflow-wrap:anywhere]",
          )}
        >
          {content}
          <RTT.Arrow width={10} height={5} className="tooltip-arrow" />
        </RTT.Content>
      </RTT.Portal>
    </RTT.Root>
  );
}
