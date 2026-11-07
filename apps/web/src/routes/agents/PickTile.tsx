import { Check } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "../../components";

/**
 * One choosable row in the attach dialogs (tools, knowledge bases): a checkbox button with an
 * icon, a body and, on the right, a check mark or a status when it cannot be picked.
 */
export function PickTile({
  checked,
  selected = checked,
  disabled,
  onToggle,
  icon,
  status,
  children,
}: {
  checked: boolean;
  /** Drawn as chosen; defaults to `checked` (an attached tool is checked but not a new pick). */
  selected?: boolean;
  disabled: boolean;
  onToggle: () => void;
  icon: ReactNode;
  /** Shown instead of the check mark (for example "Attached" or why it cannot be picked). */
  status?: ReactNode;
  children: ReactNode;
}) {
  return (
    <li>
      <button
        type="button"
        role="checkbox"
        aria-checked={checked}
        aria-disabled={disabled || undefined}
        disabled={disabled}
        onClick={onToggle}
        className={cn(
          "flex w-full min-w-0 items-center gap-3 rounded-panel border px-3.5 py-3 text-left transition-[background-color,border-color,box-shadow] duration-150",
          selected
            ? "border-accent bg-accent-soft/45 shadow-[0_0_0_1px_var(--accent)]"
            : "border-line bg-surface hover:border-accent/45 hover:bg-surface-2/60",
          disabled && "cursor-not-allowed opacity-60 hover:border-line hover:bg-surface",
          "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
        )}
      >
        {icon}
        <span className="flex min-w-0 flex-1 flex-col gap-0.5">{children}</span>
        {status ?? (
          <span
            aria-hidden
            className={cn(
              "grid size-5 shrink-0 place-items-center rounded-full border transition-[background-color,border-color,transform] duration-200",
              selected ? "scale-100 border-transparent bg-accent text-white" : "scale-90 border-line-strong bg-surface text-transparent",
            )}
          >
            <Check strokeWidth={3} className="size-3" />
          </span>
        )}
      </button>
    </li>
  );
}
