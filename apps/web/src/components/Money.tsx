import { cn } from "./cn";
import { useTicker } from "./motion";
import { formatUsd, toMicros } from "../lib/money";

export interface MoneyTextProps {
  /** Decimal USD string from the API (MoneyUsd) or micro-dollars. */
  value: string | bigint;
  /** Fractional digits. Balances use 3 (charges move in $0.001 steps). */
  places?: number;
  /** "+" on positive amounts (ledger rows). */
  signed?: boolean;
  /** Colour by sign when signed: credits in success green, debits in the default text colour. */
  toned?: boolean;
  /** Count up to the value on change (balances, totals). The last frame is the exact amount. */
  animate?: boolean;
  /** With animate: start from zero on first render. */
  fromZero?: boolean;
  className?: string;
}

/**
 * Money in tabular Geist Mono figures so columns of amounts align. The full-precision value is in
 * the title attribute for the hover.
 */
export function MoneyText({ value, places = 2, signed, toned, animate, fromZero, className }: MoneyTextProps) {
  const micros = typeof value === "bigint" ? value : toMicros(value);
  const exact = formatUsd(value, { places, signed });
  const full = micros === null ? undefined : formatUsd(micros, { places: 6, signed });
  return (
    <span
      title={full !== exact ? full : undefined}
      className={cn("font-mono tnum", toned && micros !== null && micros > 0n && "text-success-text", className)}
    >
      {animate && micros !== null ? <Animated micros={micros} places={places} signed={signed} fromZero={fromZero} exact={exact} /> : exact}
    </span>
  );
}

function Animated({ micros, places, signed, fromZero, exact }: { micros: bigint; places: number; signed?: boolean; fromZero?: boolean; exact: string }) {
  const { shown, done } = useTicker(Number(micros), { fromZero });
  return <>{done ? exact : formatUsd(BigInt(Math.round(shown)), { places, signed })}</>;
}
