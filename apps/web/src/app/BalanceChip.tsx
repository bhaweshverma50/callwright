import { Wallet } from "@phosphor-icons/react";
import { Link } from "react-router";
import { useBalance } from "../api/queries";
import { MoneyText, Skeleton, Tooltip, cn, focusRing } from "../components";
import { toMicros } from "../lib/money";

const LOW = 1_000_000n; // $1.00

/**
 * Live balance in the top bar (T042, T059, T096). A link to Billing, three decimals because
 * charges move in $0.001 steps, refetched on focus and every minute. Amber below $1, red at or
 * below zero, so the reason calls may be refused is visible before it happens.
 */
export function BalanceChip() {
  const { data, isPending, isError } = useBalance();
  const micros = data ? toMicros(data.balance_usd) : null;
  const tone = micros === null ? "neutral" : micros <= 0n ? "danger" : micros < LOW ? "amber" : "neutral";
  const hint =
    tone === "danger" ? "Balance is empty. New calls are refused until you add funds." : tone === "amber" ? "Balance is low. Add funds to keep calls running." : "Open billing";

  return (
    <Tooltip content={hint} side="bottom">
      <Link
        to="/billing"
        aria-label={data ? `Balance ${data.balance_usd} US dollars. Open billing` : "Open billing"}
        className={cn(
          "inline-flex h-7 items-center gap-1.5 rounded-full border px-2.5 text-[12.5px] transition-colors",
          tone === "danger" && "border-danger/40 bg-danger-soft text-danger-text",
          tone === "amber" && "border-amber/50 bg-amber-soft text-amber-text",
          tone === "neutral" && "border-line-strong bg-surface text-fg hover:border-fg-3",
          focusRing,
        )}
      >
        <Wallet className="size-3.5 opacity-80" aria-hidden />
        {isPending ? (
          <Skeleton className="h-3 w-12" />
        ) : isError || !data ? (
          <span className="font-mono text-fg-3">n/a</span>
        ) : (
          <MoneyText value={data.balance_usd} places={3} />
        )}
      </Link>
    </Tooltip>
  );
}
