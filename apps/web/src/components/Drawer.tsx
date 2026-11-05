import * as RD from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import type { ReactNode } from "react";
import { IconButton } from "./Button";
import { cn } from "./cn";
import { useDialogFocus } from "./dialogFocus";
import { TruncatedText } from "./TruncatedText";

export interface DrawerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  /** Small line under the title (record id, timestamp). */
  meta?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  width?: "md" | "lg" | "xl";
  side?: "right" | "left";
}

const widths = { md: "w-[440px]", lg: "w-[600px]", xl: "w-[820px]" };

/**
 * Side panel for record detail (the inspector on narrow screens, the call drawer in 006) and the
 * mobile navigation. Same focus trapping as Dialog; Escape closes it.
 */
export function Drawer({ open, onOpenChange, title, meta, actions, children, footer, width = "lg", side = "right" }: DrawerProps) {
  const focus = useDialogFocus(open);
  return (
    <RD.Root open={open} onOpenChange={onOpenChange}>
      <RD.Portal>
        <RD.Overlay className="fixed inset-0 z-40 bg-overlay backdrop-blur-[2px] data-[state=open]:animate-fade-in data-[state=closed]:animate-[fade-in_160ms_ease-in_reverse]" />
        <RD.Content
          onOpenAutoFocus={focus.onOpenAutoFocus}
          onCloseAutoFocus={focus.onCloseAutoFocus}
          className={cn(
            "fixed inset-y-0 z-50 flex max-w-[calc(100vw-24px)] flex-col bg-surface shadow-pop focus:outline-none",
            side === "right"
              ? "right-0 border-l border-line data-[state=open]:animate-[drawer-in-right_240ms_cubic-bezier(0.16,1,0.3,1)] data-[state=closed]:animate-[drawer-in-right_180ms_ease-in_reverse]"
              : "left-0 border-r border-line data-[state=open]:animate-[drawer-in-left_240ms_cubic-bezier(0.16,1,0.3,1)] data-[state=closed]:animate-[drawer-in-left_180ms_ease-in_reverse]",
            widths[width],
          )}
        >
          <header className="flex items-start gap-3 border-b border-line px-5 py-4">
            <div className="flex min-w-0 flex-1 flex-col gap-0.5">
              <RD.Title className="min-w-0 font-display text-[16px] tracking-[-0.01em] text-fg">
                <TruncatedText side="bottom">{title}</TruncatedText>
              </RD.Title>
              {meta ? (
                <RD.Description asChild>
                  <div className="min-w-0 text-[13px] text-fg-3">
                    <TruncatedText side="bottom">{meta}</TruncatedText>
                  </div>
                </RD.Description>
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
          <div data-dialog-body className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
            {children}
          </div>
          {footer && (
            <footer data-dialog-footer className="flex justify-end gap-2 border-t border-line px-5 py-3">
              {footer}
            </footer>
          )}
        </RD.Content>
      </RD.Portal>
    </RD.Root>
  );
}
