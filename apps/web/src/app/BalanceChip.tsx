import { Wallet } from "lucide-react";
import { Link } from "react-router";
import { useBalance } from "../api/queries";
import { MoneyText, Skeleton, Tooltip, cn, focusRing } from "../components";
import { LOW_BALANCE_MICROS, toMicros } from "../lib/money";
import { BILLING_PATH } from "../lib/paths";

/**
 * Live balance in the top bar (T042, T059, T096). A link to Billing, three decimals because
 * charges move in $0.001 steps, refetched on focus and every minute, and it counts to a new value
 * when the balance changes. Warning below $1, danger at or below zero, so the reason calls may be
 * refused is visible before it happens.
 */
export function BalanceChip() {
  const { data, isPending, isError } = useBalance();
  const micros = data ? toMicros(data.balance_usd) : null;
  const tone = micros === null ? "neutral" : micros <= 0n ? "danger" : micros < LOW_BALANCE_MICROS ? "warning" : "neutral";
  const hint =
    tone === "danger"
      ? "Balance is empty. New calls are refused until you add funds."
      : tone === "warning"
        ? "Balance is low. Add funds to keep calls running."
        : "Open billing";

  return (
    <Tooltip content={hint} side="bottom">
      <Link
        to={BILLING_PATH}
        aria-label={data ? `Balance ${data.balance_usd} US dollars. Open billing` : "Open billing"}
        className={cn(
          "inline-flex h-9 items-center gap-2 rounded-full border px-3 text-[13px] transition-[border-color,box-shadow,background-color] duration-150",
          tone === "danger" && "border-danger/40 bg-danger-soft text-danger-text",
          tone === "warning" && "border-warning/50 bg-warning-soft text-warning-text",
          tone === "neutral" && "border-line-strong bg-surface text-fg hover:border-accent/60",
          focusRing,
        )}
      >
        <Wallet className="size-4 opacity-80" aria-hidden />
        {isPending ? (
          <Skeleton className="h-3 w-14" />
        ) : isError || !data ? (
          <span className="text-fg-3">Unavailable</span>
        ) : (
          <MoneyText value={data.balance_usd} places={3} animate />
        )}
      </Link>
    </Tooltip>
  );
}
