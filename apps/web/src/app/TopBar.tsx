import { Building2, Menu } from "lucide-react";
import type { ReactNode } from "react";
import { useMe } from "../api/queries";
import { IconButton, Skeleton, TruncatedText } from "../components";
import { BalanceChip } from "./BalanceChip";
import { UserMenu } from "./UserMenu";

/**
 * Top bar: navigation button on small screens, workspace name, live balance, user menu. `assist`
 * holds the assistant controls on full-height editors, where the floating dock would cover the canvas.
 */
export function TopBar({ onOpenNav, assist }: { onOpenNav: () => void; assist?: ReactNode }) {
  const { data: me, isPending } = useMe();
  return (
    <header className="sticky top-0 z-30 flex h-[60px] items-center justify-between gap-3 border-b border-line bg-bg/80 px-4 backdrop-blur-md sm:px-6 lg:px-10">
      <div className="flex min-w-0 items-center gap-2">
        <IconButton label="Open navigation" tooltipSide="bottom" className="-ml-2 lg:hidden" onClick={onOpenNav}>
          <Menu className="size-5" aria-hidden />
        </IconButton>
        <Building2 className="hidden size-4 shrink-0 text-fg-3 sm:block" aria-hidden />
        {isPending ? (
          <Skeleton className="h-3.5 w-36" />
        ) : (
          <TruncatedText side="bottom" className="text-[14px] font-medium text-fg">
            {me?.workspace.name}
          </TruncatedText>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-2 sm:gap-3">
        {assist}
        <BalanceChip />
        <UserMenu />
      </div>
    </header>
  );
}
