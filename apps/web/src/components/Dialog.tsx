import * as RD from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import type { ReactNode } from "react";
import { Button, IconButton } from "./Button";
import { cn } from "./cn";
import { useDialogFocus } from "./dialogFocus";

export interface DialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  description?: ReactNode;
  icon?: ReactNode;
  children?: ReactNode;
  /** Buttons row, right aligned. */
  footer?: ReactNode;
  size?: "sm" | "md" | "lg";
  /** Alert dialogs cannot be dismissed by clicking outside. */
  role?: "dialog" | "alertdialog";
}

const widths = { sm: "max-w-[420px]", md: "max-w-[540px]", lg: "max-w-[740px]" };

/** Centered modal. Focus is trapped inside and returns to the trigger on close. */
export function Dialog({ open, onOpenChange, title, description, icon, children, footer, size = "md", role = "dialog" }: DialogProps) {
  const focus = useDialogFocus(open);
  return (
    <RD.Root open={open} onOpenChange={onOpenChange}>
      <RD.Portal>
        <RD.Overlay className="fixed inset-0 z-40 bg-overlay backdrop-blur-[2px] data-[state=open]:animate-fade-in data-[state=closed]:animate-[fade-in_140ms_ease-in_reverse]" />
        <RD.Content
          role={role}
          onOpenAutoFocus={focus.onOpenAutoFocus}
          onCloseAutoFocus={focus.onCloseAutoFocus}
          onPointerDownOutside={role === "alertdialog" ? (e) => e.preventDefault() : undefined}
          className={cn(
            "fixed left-1/2 top-[14vh] z-50 flex max-h-[calc(100dvh-14vh-16px)] w-[calc(100vw-32px)] -translate-x-1/2 flex-col",
            "rounded-panel border border-line bg-surface shadow-pop focus:outline-none",
            "data-[state=open]:animate-pop-in data-[state=closed]:animate-[pop-in_140ms_ease-in_reverse]",
            widths[size],
          )}
        >
          <div className="flex shrink-0 items-start justify-between gap-4 px-5 pb-1 pt-5">
            <div className="flex items-start gap-3">
              {icon && (
                <span className="grid size-9 shrink-0 place-items-center rounded-control bg-accent-soft text-accent-text [&_svg]:size-[18px]">
                  {icon}
                </span>
              )}
              <div className="flex flex-col gap-1">
                <RD.Title className="font-display text-[17px] tracking-[-0.01em] text-fg">{title}</RD.Title>
                {description ? (
                  <RD.Description className="text-[14px] leading-relaxed text-fg-2">{description}</RD.Description>
                ) : (
                  <RD.Description className="sr-only">{typeof title === "string" ? title : "Dialog"}</RD.Description>
                )}
              </div>
            </div>
            {role === "dialog" && (
              <RD.Close asChild>
                <IconButton label="Close" className="-mr-2 -mt-1">
                  <X className="size-4" aria-hidden />
                </IconButton>
              </RD.Close>
            )}
          </div>
          {/* Tall content scrolls inside the dialog so the footer stays on screen. */}
          {children && (
            <div data-dialog-body className="min-h-0 overflow-y-auto px-5 py-3 text-[14px] text-fg-2">
              {children}
            </div>
          )}
          {footer && (
            <div data-dialog-footer className="flex shrink-0 justify-end gap-2 border-t border-line px-5 py-3.5">
              {footer}
            </div>
          )}
        </RD.Content>
      </RD.Portal>
    </RD.Root>
  );
}

export interface ConfirmDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  description?: ReactNode;
  icon?: ReactNode;
  confirmLabel: string;
  cancelLabel?: string;
  tone?: "default" | "danger";
  pending?: boolean;
  onConfirm: () => void;
}

/** Two-choice alert dialog. The safe choice (cancel) gets initial focus. */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  icon,
  confirmLabel,
  cancelLabel = "Cancel",
  tone = "default",
  pending,
  onConfirm,
}: ConfirmDialogProps) {
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={title}
      description={description}
      icon={icon}
      size="sm"
      role="alertdialog"
      footer={
        <>
          <Button autoFocus onClick={() => onOpenChange(false)}>
            {cancelLabel}
          </Button>
          <Button variant={tone === "danger" ? "danger" : "primary"} pending={pending} onClick={onConfirm}>
            {confirmLabel}
          </Button>
        </>
      }
    />
  );
}
