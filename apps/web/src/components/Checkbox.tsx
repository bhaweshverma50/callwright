import { Check, Minus } from "lucide-react";
import { cn, focusRing } from "./cn";

/** Row checkbox (a button with role checkbox), as in Call History and the simulation pickers. */
export function Checkbox({ checked, mixed, onChange, label }: { checked: boolean; mixed?: boolean; onChange: () => void; label: string }) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={mixed ? "mixed" : checked}
      aria-label={label}
      onClick={(e) => {
        e.stopPropagation();
        onChange();
      }}
      className={cn(
        "grid size-[18px] shrink-0 cursor-pointer place-items-center rounded-[5px] border transition-[background-color,border-color,transform] duration-150 active:scale-90",
        checked || mixed ? "bg-accent border-transparent text-white" : "border-line-strong bg-surface hover:border-accent",
        focusRing,
      )}
    >
      {mixed ? <Minus className="size-3" strokeWidth={3} aria-hidden /> : checked ? <Check className="size-3" strokeWidth={3} aria-hidden /> : null}
    </button>
  );
}
