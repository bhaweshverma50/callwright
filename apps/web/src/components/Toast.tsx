import * as RT from "@radix-ui/react-toast";
import { CircleAlert, CircleCheck, Info, X } from "lucide-react";
import { useSyncExternalStore, type ReactNode } from "react";
import { cn, focusRing } from "./cn";
import { Tooltip } from "./Tooltip";

export type ToastTone = "success" | "info" | "error";

export interface ToastInput {
  title: ReactNode;
  description?: ReactNode;
  tone?: ToastTone;
  /** Milliseconds; errors stay longer by default. */
  duration?: number;
  /** One follow-up action ("Open copy", "Undo"). The label also names it for screen readers. */
  action?: { label: string; onClick: () => void };
}

interface ToastItem extends ToastInput {
  id: number;
  open: boolean;
}

let items: ToastItem[] = [];
let seq = 0;
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());

/** Show a transient message from anywhere (mutations, guards). Inline errors stay inline. */
export function toast(input: ToastInput) {
  const item: ToastItem = { tone: "info", ...input, id: ++seq, open: true };
  items = [...items.slice(-3), item];
  emit();
  return item.id;
}

function close(id: number) {
  items = items.map((t) => (t.id === id ? { ...t, open: false } : t));
  emit();
  window.setTimeout(() => {
    items = items.filter((t) => t.id !== id);
    emit();
  }, 220);
}

function useToasts() {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => items,
    () => items,
  );
}

const icons: Record<ToastTone, ReactNode> = {
  success: <CircleCheck className="size-4 text-success-text" aria-hidden />,
  info: <Info className="size-4 text-accent-text" aria-hidden />,
  error: <CircleAlert className="size-4 text-danger-text" aria-hidden />,
};

/** Mount once near the root. Toasts stack bottom right, slide in and are announced politely. */
export function Toaster() {
  const list = useToasts();
  return (
    <RT.Provider swipeDirection="right">
      {list.map((t) => (
        <RT.Root
          key={t.id}
          open={t.open}
          duration={t.duration ?? (t.tone === "error" ? 8000 : t.action ? 7000 : 4000)}
          type={t.tone === "error" ? "foreground" : "background"}
          onOpenChange={(o) => !o && close(t.id)}
          className={cn(
            "relative flex w-[360px] max-w-[calc(100vw-32px)] items-start gap-3 overflow-hidden rounded-panel border border-line bg-surface py-3 pl-4 pr-3 shadow-pop",
            "data-[state=open]:animate-[toast-in_240ms_cubic-bezier(0.16,1,0.3,1)] data-[state=closed]:animate-[toast-in_160ms_ease-in_reverse] data-[swipe=end]:translate-x-full",
          )}
        >
          <span className="mt-0.5">{icons[t.tone ?? "info"]}</span>
          <div className="flex min-w-0 flex-1 flex-col gap-0.5">
            <RT.Title className="text-[13.5px] font-medium text-fg">{t.title}</RT.Title>
            {t.description && <RT.Description className="text-[12.5px] leading-relaxed text-fg-2">{t.description}</RT.Description>}
            {t.action && (
              <RT.Action
                altText={t.action.label}
                onClick={t.action.onClick}
                className={cn("link-underline mt-1 w-fit cursor-pointer rounded-inline text-[12.5px] font-medium text-accent-text", focusRing)}
              >
                {t.action.label}
              </RT.Action>
            )}
          </div>
          <Tooltip content="Dismiss">
            <RT.Close aria-label="Dismiss" className={cn("cursor-pointer rounded-inline p-1 text-fg-3 hover:bg-surface-3 hover:text-fg", focusRing)}>
              <X className="size-3.5" aria-hidden />
            </RT.Close>
          </Tooltip>
        </RT.Root>
      ))}
      <RT.Viewport className="fixed bottom-4 right-4 z-[60] flex flex-col gap-2 outline-none" />
    </RT.Provider>
  );
}
