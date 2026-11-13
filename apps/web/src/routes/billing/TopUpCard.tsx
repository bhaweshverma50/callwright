import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CreditCard, Lock } from "lucide-react";
import { useRef, useState, type FormEvent, type Ref } from "react";
import { idempotencyKey } from "../../lib/idempotency";
import { fieldErrors, problemMessage } from "../../api/problems";
import { createCheckoutSession, qk } from "../../api/queries";
import type { Balance } from "../../api/types";
import { Button, Chip, Field, Input, Panel, Tooltip } from "../../components";
import { checkTopUpAmount, formatUsd, TOP_UP_RANGE } from "../../lib/money";
import { talkMinutes } from "../../api/pricing";

export const PRESETS = ["25", "100", "500", "1000"] as const;

/** Balance before checkout, so the return page can tell when the new credit has landed. */
export const CHECKOUT_BEFORE_KEY = "cw.checkout.before";

/**
 * Add funds (T057, T101, US2.5, US2.6, FR-008). Presets only fill the amount; checkout starts
 * from one explicit button that names the amount. Invalid amounts are explained inline and the
 * disabled button says why. One idempotency key per amount, so a double click opens one session.
 * With a stack price, the amount is also shown as talk time.
 */
export function TopUpCard({
  inputRef,
  perMinuteMicros,
  className,
}: {
  inputRef?: Ref<HTMLInputElement>;
  perMinuteMicros?: bigint | null;
  className?: string;
}) {
  const [amount, setAmount] = useState("");
  const [touched, setTouched] = useState(false);
  const keyRef = useRef<{ amount: string; key: string } | null>(null);
  const qc = useQueryClient();

  const check = checkTopUpAmount(amount);
  const showError = touched && amount.trim() !== "" && !check.ok;
  const reason = check.ok ? null : check.reason;

  const checkout = useMutation({
    mutationFn: async (normalized: string) => {
      if (keyRef.current?.amount !== normalized) keyRef.current = { amount: normalized, key: idempotencyKey() };
      return createCheckoutSession(normalized, keyRef.current.key);
    },
    onSuccess: (s) => {
      const before = qc.getQueryData<Balance>(qk.balance)?.balance_usd;
      try {
        if (before) sessionStorage.setItem(CHECKOUT_BEFORE_KEY, before);
      } catch {
        /* the return page falls back to the first balance it sees */
      }
      window.location.assign(s.checkout_url);
    },
  });

  const serverFieldError = fieldErrors(checkout.error).amount_usd;
  const formError = checkout.error && !serverFieldError ? problemMessage(checkout.error) : null;

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    setTouched(true);
    if (check.ok && !checkout.isPending) checkout.mutate(check.normalized);
  };

  const label = check.ok ? `Add funds ${formatUsd(check.micros, { places: 2 })}` : "Add funds";
  const disabledWhy = !check.ok ? (amount.trim() === "" ? "Pick or enter an amount first." : reason) : null;
  const minutes = check.ok && perMinuteMicros ? talkMinutes(check.micros, perMinuteMicros) : null;

  return (
    <Panel
      title="Add funds"
      description="Paid by card through secure hosted checkout. Credit appears once the payment is confirmed."
      icon={<CreditCard />}
      className={className}
    >
      {/* Narrow card: presets above the amount. Wide card (the stacked layout below xl): amount and pay
          button on the left, presets on the same line to the right, so nothing stretches across the page. */}
      <div className="@container">
        <form
          onSubmit={onSubmit}
          noValidate
          className="grid grid-cols-[minmax(0,1fr)] gap-3.5 @[40rem]:grid-cols-[minmax(0,26rem)_auto] @[40rem]:justify-between @[40rem]:gap-x-8"
        >
          <div
            role="group"
            aria-label="Preset amounts"
            className="grid grid-cols-4 gap-2 @[40rem]:col-start-2 @[40rem]:row-start-1 @[40rem]:mt-[26px] @[40rem]:flex"
          >
            {PRESETS.map((p) => {
              const value = `${p}.00`;
              return (
                <Chip
                  key={p}
                  className="justify-center px-2 @[40rem]:min-w-[72px] @[40rem]:px-3"
                  selected={check.ok && check.normalized === value}
                  onClick={() => {
                    setAmount(value);
                    setTouched(true);
                    checkout.reset();
                  }}
                >
                  {formatUsd(p, { places: 0 })}
                </Chip>
              );
            })}
          </div>

          <Field
            className="@[40rem]:col-start-1 @[40rem]:row-start-1"
            label="Amount"
            error={serverFieldError ?? (showError ? reason : null)}
            hint={
              minutes !== null ? (
                <>
                  About <span className="font-mono text-fg-2 tnum">{minutes.toLocaleString()}</span> minutes of calls on your current stack.
                </>
              ) : (
                `${TOP_UP_RANGE}, in whole cents.`
              )
            }
          >
            {({ id, describedBy, invalid }) => (
              // The pay button sits on the amount's line, so the card stays as short as the balance beside it.
              <div className="flex items-start gap-2">
                <div className="min-w-0 flex-1">
                  <Input
                    ref={inputRef}
                    id={id}
                    prefix="$"
                    inputMode="decimal"
                    autoComplete="off"
                    placeholder="0.00"
                    className="font-mono tnum"
                    value={amount}
                    onChange={(e) => {
                      setAmount(e.target.value);
                      checkout.reset();
                    }}
                    onBlur={() => setTouched(true)}
                    aria-describedby={describedBy}
                    aria-invalid={invalid}
                  />
                </div>
                <Tooltip content={disabledWhy ?? ""} enabled={Boolean(disabledWhy)}>
                  {/* A wrapper keeps the tooltip reachable while the button itself is disabled. */}
                  <span
                    tabIndex={disabledWhy ? 0 : -1}
                    className="block rounded-control focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
                    aria-describedby={disabledWhy ? "topup-why" : undefined}
                  >
                    <Button type="submit" variant="primary" disabled={!check.ok} pending={checkout.isPending} icon={<Lock aria-hidden />}>
                      {label}
                    </Button>
                  </span>
                </Tooltip>
              </div>
            )}
          </Field>

          {formError && (
            <p role="alert" className="text-[13px] text-danger-text @[40rem]:col-span-2">
              {formError}
            </p>
          )}

          {disabledWhy && (
            <p id="topup-why" className="sr-only">
              {disabledWhy}
            </p>
          )}
        </form>
      </div>
    </Panel>
  );
}
