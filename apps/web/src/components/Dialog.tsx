import * as RD from "@radix-ui/react-dialog";
import { X } from "@phosphor-icons/react";
import type { ReactNode } from "react";
import { Button, IconButton } from "./Button";
import { cn } from "./cn";

export interface DialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  description?: ReactNode;
  children?: ReactNode;
  /** Buttons row, right aligned. */
  footer?: ReactNode;
  size?: "sm" | "md" | "lg";
  /** Alert dialogs cannot be dismissed by clicking outside. */
  role?: "dialog" | "alertdialog";
}

const widths = { sm: "max-w-[400px]", md: "max-w-[520px]", lg: "max-w-[720px]" };

/** Centered modal. Focus is trapped inside and returns to the trigger on close. */
export function Dialog({ open, onOpenChange, title, description, children, footer, size = "md", role = "dialog" }: DialogProps) {
  return (
    <RD.Root open={open} onOpenChange={onOpenChange}>
      <RD.Portal>
        <RD.Overlay className="fixed inset-0 z-40 bg-overlay animate-fade-in" />
        <RD.Content
          role={role}
          onPointerDownOutside={role === "alertdialog" ? (e) => e.preventDefault() : undefined}
          className={cn(
            "fixed left-1/2 top-[12vh] z-50 w-[calc(100vw-32px)] -translate-x-1/2",
            "rounded-panel border border-line bg-surface shadow-pop animate-pop-in focus:outline-none",
            widths[size],
          )}
        >
          <div className="flex items-start justify-between gap-4 px-5 pb-1 pt-4">
            <div className="flex flex-col gap-1">
              <RD.Title className="font-display text-[17px] font-semibold tracking-[-0.01em] text-fg">{title}</RD.Title>
              {description ? (
                <RD.Description className="text-[13px] leading-relaxed text-fg-2">{description}</RD.Description>
              ) : (
                <RD.Description className="sr-only">{typeof title === "string" ? title : "Dialog"}</RD.Description>
              )}
            </div>
            {role === "dialog" && (
              <RD.Close asChild>
                <IconButton label="Close" className="-mr-2 -mt-1">
                  <X className="size-4" aria-hidden />
                </IconButton>
              </RD.Close>
            )}
          </div>
          {children && <div className="px-5 py-3 text-[13px] text-fg-2">{children}</div>}
          {footer && <div className="flex justify-end gap-2 border-t border-line px-5 py-3">{footer}</div>}
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
