import { Waveform } from "@phosphor-icons/react";
import { cn } from "./cn";

/** Callwright mark: a waveform glyph in a teal tile, then the wordmark in the display face. */
export function Logo({ compact, className }: { compact?: boolean; className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2", className)}>
      <span className="grid size-7 shrink-0 place-items-center rounded-[7px] bg-accent text-accent-fg">
        <Waveform weight="bold" className="size-4" aria-hidden />
      </span>
      {!compact && <span className="font-display text-[16px] font-semibold tracking-[-0.02em] text-fg">Callwright</span>}
      {compact && <span className="sr-only">Callwright</span>}
    </span>
  );
}
