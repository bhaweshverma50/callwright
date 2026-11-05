import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CreditCard, ExternalLink, Lock } from "lucide-react";
import { useRef, useState, type FormEvent, type Ref } from "react";
import { api, unwrap } from "../../api/client";
import { fieldErrors, problemMessage } from "../../api/problems";
import { qk } from "../../api/queries";
import type { Balance } from "../../api/types";
import { Button, Chip, Field, Input, Panel, Tooltip } from "../../components";
import { checkTopUpAmount, formatUsd } from "../../lib/money";
import { talkMinutes } from "../../lib/stack";

export const PRESETS = ["25", "100", "500", "1000"] as const;

/** Where the browser goes for hosted checkout. Indirection so tests can observe it. */
export const checkoutNavigator = { go: (url: string) => window.location.assign(url) };

/** Balance before checkout, so the return page can tell when the new credit has landed. */
export const CHECKOUT_BEFORE_KEY = "cw.checkout.before";

function newKey() {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

/**
 * Add funds (T057, T101, US2.5, US2.6, FR-008). Presets only fill the amount; checkout starts
 * from one explicit button that names the amount. Invalid amounts are explained inline and the
 * disabled button says why. One idempotency key per amount, so a double click opens one session.
 * With a stack price, the amount is also shown as talk time.
 */
export function TopUpCard({ inputRef, perMinuteMicros }: { inputRef?: Ref<HTMLInputElement>; perMinuteMicros?: bigint | null }) {
  const [amount, setAmount] = useState("");
  const [touched, setTouched] = useState(false);
  const keyRef = useRef<{ amount: string; key: string } | null>(null);
  const qc = useQueryClient();

  const check = checkTopUpAmount(amount);
  const showError = touched && amount.trim() !== "" && !check.ok;
  const reason = check.ok ? null : check.reason;

  const checkout = useMutation({
    mutationFn: async (normalized: string) => {
      if (keyRef.current?.amount !== normalized) keyRef.current = { amount: normalized, key: newKey() };
      return unwrap(
        api.POST("/billing/checkout-sessions", {
          body: { amount_usd: normalized },
          params: { header: { "Idempotency-Key": keyRef.current.key } },
        }),
      );
    },
    onSuccess: (s) => {
      const before = qc.getQueryData<Balance>(qk.balance)?.balance_usd;
      try {
        if (before) sessionStorage.setItem(CHECKOUT_BEFORE_KEY, before);
      } catch {
        /* the return page falls back to the first balance it sees */
      }
      checkoutNavigator.go(s.checkout_url);
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
    <Panel title="Add funds" description="Paid by card through secure hosted checkout." icon={<CreditCard />}>
      <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4">
        <div role="group" aria-label="Preset amounts" className="grid grid-cols-4 gap-2">
          {PRESETS.map((p) => {
            const value = `${p}.00`;
            return (
              <Chip
                key={p}
                className="justify-center px-2"
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
          label="Amount"
          error={serverFieldError ?? (showError ? reason : null)}
          hint={
            minutes !== null ? (
              <>
                About <span className="font-mono text-fg-2 tnum">{minutes.toLocaleString()}</span> minutes of calls on your current stack.
              </>
            ) : (
              "Between $5 and $10,000, in whole cents."
            )
          }
        >
          {({ id, describedBy, invalid }) => (
            <Input
              ref={inputRef}
              id={id}
              prefix="$"
              inputMode="decimal"
              autoComplete="off"
              placeholder="0.00"
              inputSize="lg"
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
          )}
        </Field>

        {formError && (
          <p role="alert" className="text-[13px] text-danger-text">
            {formError}
          </p>
        )}

        <Tooltip content={disabledWhy ?? ""} enabled={Boolean(disabledWhy)}>
          {/* A wrapper keeps the tooltip reachable while the button itself is disabled. */}
          <span
            tabIndex={disabledWhy ? 0 : -1}
            className="block rounded-control focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
            aria-describedby={disabledWhy ? "topup-why" : undefined}
          >
            <Button
              type="submit"
              variant="primary"
              size="lg"
              className="w-full"
              disabled={!check.ok}
              pending={checkout.isPending}
              icon={<Lock aria-hidden />}
            >
              {label}
            </Button>
          </span>
        </Tooltip>
        {disabledWhy && (
          <p id="topup-why" className="sr-only">
            {disabledWhy}
          </p>
        )}
        <p className="flex items-start gap-2 text-[13px] leading-relaxed text-fg-3">
          <ExternalLink className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          You return here after paying. Credit appears once the payment is confirmed.
        </p>
      </form>
    </Panel>
  );
}
