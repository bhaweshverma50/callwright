import * as RT from "@radix-ui/react-toast";
import { CheckCircle, Info, WarningCircle, X } from "@phosphor-icons/react";
import { useSyncExternalStore, type ReactNode } from "react";
import { cn, focusRing } from "./cn";

export type ToastTone = "success" | "info" | "error";

export interface ToastInput {
  title: ReactNode;
  description?: ReactNode;
  tone?: ToastTone;
  /** Milliseconds; errors stay longer by default. */
  duration?: number;
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
  }, 200);
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
  success: <CheckCircle weight="fill" className="size-4 text-success-text" aria-hidden />,
  info: <Info weight="fill" className="size-4 text-accent-text" aria-hidden />,
  error: <WarningCircle weight="fill" className="size-4 text-danger-text" aria-hidden />,
};

/** Mount once near the root. Toasts stack bottom right and are announced politely. */
export function Toaster() {
  const list = useToasts();
  return (
    <RT.Provider swipeDirection="right">
      {list.map((t) => (
        <RT.Root
          key={t.id}
          open={t.open}
          duration={t.duration ?? (t.tone === "error" ? 8000 : 4000)}
          type={t.tone === "error" ? "foreground" : "background"}
          onOpenChange={(o) => !o && close(t.id)}
          className={cn(
            "flex w-[360px] max-w-[calc(100vw-32px)] items-start gap-2.5 rounded-panel border border-line bg-surface px-3.5 py-3 shadow-pop",
            "data-[state=open]:animate-slide-in-right data-[state=closed]:animate-fade-in data-[swipe=end]:translate-x-full",
          )}
        >
          <span className="mt-0.5">{icons[t.tone ?? "info"]}</span>
          <div className="flex min-w-0 flex-1 flex-col gap-0.5">
            <RT.Title className="text-[13px] font-medium text-fg">{t.title}</RT.Title>
            {t.description && <RT.Description className="text-[12.5px] leading-relaxed text-fg-2">{t.description}</RT.Description>}
          </div>
          <RT.Close aria-label="Dismiss" className={cn("rounded-[4px] p-0.5 text-fg-3 hover:text-fg", focusRing)}>
            <X className="size-3.5" aria-hidden />
          </RT.Close>
        </RT.Root>
      ))}
      <RT.Viewport className="fixed bottom-4 right-4 z-[60] flex flex-col gap-2 outline-none" />
    </RT.Provider>
  );
}
