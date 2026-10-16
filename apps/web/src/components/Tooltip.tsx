import * as RTT from "@radix-ui/react-tooltip";
import type { ReactElement, ReactNode } from "react";
import { cn } from "./cn";

export const TooltipProvider = RTT.Provider;

export interface TooltipProps {
  content: ReactNode;
  children: ReactElement;
  side?: "top" | "right" | "bottom" | "left";
  /** When false the tooltip never opens (for example nav labels while the sidebar is expanded). */
  enabled?: boolean;
}

/** Short label on hover and keyboard focus; fades in. Never the only place important text lives. */
export function Tooltip({ content, children, side = "top", enabled = true }: TooltipProps) {
  if (!enabled) return children;
  return (
    <RTT.Root>
      <RTT.Trigger asChild>{children}</RTT.Trigger>
      <RTT.Portal>
        <RTT.Content
          side={side}
          sideOffset={8}
          className={cn(
            "z-50 rounded-control bg-console px-2.5 py-1.5 text-[12px] font-medium text-console-fg shadow-pop",
            "data-[state=delayed-open]:animate-fade-in data-[state=instant-open]:animate-fade-in data-[state=closed]:animate-[fade-in_100ms_ease-in_reverse]",
          )}
        >
          {content}
        </RTT.Content>
      </RTT.Portal>
    </RTT.Root>
  );
}
