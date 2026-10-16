import { cn } from "./cn";
import { formatUsd, toMicros } from "../lib/money";

export interface MoneyTextProps {
  /** Decimal USD string from the API (MoneyUsd) or micro-dollars. */
  value: string | bigint;
  /** Fractional digits. Balances use 3 (charges move in $0.001 steps). */
  places?: number;
  /** "+" on positive amounts and tone by sign (ledger rows). */
  signed?: boolean;
  /** Colour by sign when signed: credits in success green, debits in the default text colour. */
  toned?: boolean;
  className?: string;
}

/**
 * Money in tabular mono figures so columns of amounts align. The full-precision value is kept
 * in the title attribute for the hover.
 */
export function MoneyText({ value, places = 2, signed, toned, className }: MoneyTextProps) {
  const micros = typeof value === "bigint" ? value : toMicros(value);
  const text = formatUsd(value, { places, signed });
  const full = micros === null ? undefined : formatUsd(micros, { places: 6, signed });
  return (
    <span
      title={full !== text ? full : undefined}
      className={cn(
        "font-mono tnum",
        toned && micros !== null && micros > 0n && "text-success-text",
        className,
      )}
    >
      {text}
    </span>
  );
}
