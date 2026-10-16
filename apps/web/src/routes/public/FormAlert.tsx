import { Info, WarningCircle } from "@phosphor-icons/react";
import type { ReactNode } from "react";
import { cn } from "../../components";

/** Form-level message above the fields: error (red), warning (amber) or info (teal). */
export function FormAlert({ tone = "error", children, action }: { tone?: "error" | "warning" | "info"; children: ReactNode; action?: ReactNode }) {
  const Icon = tone === "info" ? Info : WarningCircle;
  return (
    <div
      role={tone === "info" ? "status" : "alert"}
      className={cn(
        "mb-5 flex items-start gap-2.5 rounded-control border px-3 py-2.5 text-[13px] leading-relaxed",
        tone === "error" && "border-danger/30 bg-danger-soft text-danger-text",
        tone === "warning" && "border-amber/40 bg-amber-soft text-amber-text",
        tone === "info" && "border-accent/30 bg-accent-soft text-accent-text",
      )}
    >
      <Icon weight="fill" className="mt-0.5 size-4 shrink-0" aria-hidden />
      <div className="flex flex-1 flex-col gap-1.5">
        <div>{children}</div>
        {action}
      </div>
    </div>
  );
}
