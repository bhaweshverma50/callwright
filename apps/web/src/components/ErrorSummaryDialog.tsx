import { CircleAlert } from "lucide-react";
import { Button } from "./Button";
import { Dialog } from "./Dialog";

export interface ErrorSummaryItem {
  /** Field or section the error belongs to, as the user sees it ("Workspace name"). */
  label: string;
  message: string;
  /** Element id to focus when the user picks this error. */
  targetId?: string;
}

/**
 * Aggregated validation errors for long forms (T085, reused by 002's agent editor). Each entry
 * jumps to its field. Messages come from problemMessage/fieldErrors, never raw server text.
 */
export function ErrorSummaryDialog({
  open,
  onOpenChange,
  title = "Fix these before saving",
  items,
  onJump,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title?: string;
  items: ErrorSummaryItem[];
  /** Runs before focus moves, so a form can reveal the field first (switch tab, expand a section). */
  onJump?: (item: ErrorSummaryItem) => void;
}) {
  const jump = (it: ErrorSummaryItem) => {
    onOpenChange(false);
    onJump?.(it);
    if (!it.targetId) return;
    window.setTimeout(
      () => {
        const el = document.getElementById(it.targetId!);
        el?.scrollIntoView({ block: "center", behavior: "smooth" });
        el?.focus({ preventScroll: true });
      },
      onJump ? 160 : 50,
    );
  };
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={title}
      description={`${items.length} ${items.length === 1 ? "problem" : "problems"} found.`}
      footer={<Button onClick={() => onOpenChange(false)}>Close</Button>}
    >
      <ul className="flex flex-col gap-1">
        {items.map((it, i) => (
          <li key={i}>
            <button
              type="button"
              onClick={() => jump(it)}
              className="flex w-full items-start gap-2 rounded-control px-2 py-1.5 text-left hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-ring"
            >
              <CircleAlert className="mt-0.5 size-3.5 shrink-0 text-danger-text" aria-hidden />
              <span>
                <span className="font-medium text-fg">{it.label}</span>
                <span className="text-fg-2">: {it.message}</span>
              </span>
            </button>
          </li>
        ))}
      </ul>
    </Dialog>
  );
}
