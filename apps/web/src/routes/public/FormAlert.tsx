import { CircleAlert, Info, TriangleAlert } from "lucide-react";
import { motion } from "motion/react";
import type { ReactNode } from "react";
import { cn } from "../../components";

/** Form-level message above the fields: error (danger), warning or info (cobalt). */
export function FormAlert({ tone = "error", children, action }: { tone?: "error" | "warning" | "info"; children: ReactNode; action?: ReactNode }) {
  const Icon = tone === "info" ? Info : tone === "warning" ? TriangleAlert : CircleAlert;
  return (
    <motion.div
      role={tone === "info" ? "status" : "alert"}
      initial={{ opacity: 0, y: -4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
      className={cn(
        "mb-5 flex items-start gap-2.5 rounded-control border px-3.5 py-3 text-[13.5px] leading-relaxed",
        tone === "error" && "border-danger/30 bg-danger-soft text-danger-text",
        tone === "warning" && "border-warning/40 bg-warning-soft text-warning-text",
        tone === "info" && "border-accent/25 bg-accent-soft text-accent-text",
      )}
    >
      <Icon className="mt-0.5 size-4 shrink-0" aria-hidden />
      <div className="flex flex-1 flex-col gap-2">
        <div>{children}</div>
        {action}
      </div>
    </motion.div>
  );
}
