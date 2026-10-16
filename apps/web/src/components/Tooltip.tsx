import * as RTT from "@radix-ui/react-tooltip";
import type { ReactElement, ReactNode } from "react";
import { cn } from "./cn";

export const TooltipProvider = RTT.Provider;

export interface TooltipProps {
  content: ReactNode;
  children: ReactElement;
  side?: "top" | "right" | "bottom" | "left";
  /** When false the tooltip never opens (for example nav labels while the rail is expanded). */
  enabled?: boolean;
}

/** Short label on hover and keyboard focus. Never the only place important text lives. */
export function Tooltip({ content, children, side = "top", enabled = true }: TooltipProps) {
  if (!enabled) return children;
  return (
    <RTT.Root>
      <RTT.Trigger asChild>{children}</RTT.Trigger>
      <RTT.Portal>
        <RTT.Content
          side={side}
          sideOffset={6}
          className={cn(
            "z-50 rounded-[5px] bg-fg px-2 py-1 text-[12px] font-medium text-bg shadow-pop animate-fade-in",
          )}
        >
          {content}
        </RTT.Content>
      </RTT.Portal>
    </RTT.Root>
  );
}
