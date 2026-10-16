import * as RP from "@radix-ui/react-popover";
import { Receipt } from "@phosphor-icons/react";
import type { CostBreakdown } from "../../api/types";
import { CostBreakdownCard, cn, focusRing } from "../../components";

/** Itemised cost for a call-charge row (T072). Opens on click or Enter; Escape closes it. */
export function CostBreakdownPopover({ breakdown }: { breakdown: CostBreakdown }) {
  return (
    <RP.Root>
      <RP.Trigger
        aria-label="Show cost breakdown"
        className={cn(
          "inline-flex h-6 items-center gap-1 rounded-[5px] px-1.5 text-[12px] text-fg-3 transition-colors hover:bg-surface-3 hover:text-fg",
          "data-[state=open]:bg-surface-3 data-[state=open]:text-fg",
          focusRing,
        )}
      >
        <Receipt className="size-3.5" aria-hidden />
        Breakdown
      </RP.Trigger>
      <RP.Portal>
        <RP.Content side="left" align="start" sideOffset={8} collisionPadding={16} className="z-50 w-[440px] max-w-[calc(100vw-32px)] animate-pop-in outline-none">
          <CostBreakdownCard breakdown={breakdown} className="shadow-pop" />
        </RP.Content>
      </RP.Portal>
    </RP.Root>
  );
}
