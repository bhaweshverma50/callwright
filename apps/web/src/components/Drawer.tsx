import * as RD from "@radix-ui/react-dialog";
import { X } from "@phosphor-icons/react";
import type { ReactNode } from "react";
import { IconButton } from "./Button";
import { cn } from "./cn";

export interface DrawerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  /** Small mono line under the title (record id, timestamp). */
  meta?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  width?: "md" | "lg" | "xl";
}

const widths = { md: "w-[440px]", lg: "w-[600px]", xl: "w-[820px]" };

/**
 * Right-side panel for record detail (for example the call drawer at `/calls?call=<id>` in 006).
 * Same focus trapping as Dialog; Escape closes it.
 */
export function Drawer({ open, onOpenChange, title, meta, actions, children, footer, width = "lg" }: DrawerProps) {
  return (
    <RD.Root open={open} onOpenChange={onOpenChange}>
      <RD.Portal>
        <RD.Overlay className="fixed inset-0 z-40 bg-overlay animate-fade-in" />
        <RD.Content
          className={cn(
            "fixed inset-y-0 right-0 z-50 flex max-w-[calc(100vw-24px)] flex-col border-l border-line bg-surface shadow-pop",
            "animate-slide-in-right focus:outline-none",
            widths[width],
          )}
        >
          <header className="flex items-start gap-3 border-b border-line px-5 py-3.5">
            <div className="flex min-w-0 flex-1 flex-col gap-0.5">
              <RD.Title className="truncate font-display text-[16px] font-semibold tracking-[-0.01em] text-fg">{title}</RD.Title>
              {meta ? (
                <RD.Description className="truncate font-mono text-[11.5px] text-fg-3">{meta}</RD.Description>
              ) : (
                <RD.Description className="sr-only">Details</RD.Description>
              )}
            </div>
            {actions}
            <RD.Close asChild>
              <IconButton label="Close panel" className="-mr-2">
                <X className="size-4" aria-hidden />
              </IconButton>
            </RD.Close>
          </header>
          <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
          {footer && <footer className="flex justify-end gap-2 border-t border-line px-5 py-3">{footer}</footer>}
        </RD.Content>
      </RD.Portal>
    </RD.Root>
  );
}
