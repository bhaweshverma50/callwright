import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, CircleAlert, CircleCheck, CreditCard, FlaskConical, Lock } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useRef, useState, type FormEvent, type ReactNode } from "react";
import { Link, useParams } from "react-router";
import { ApiError, toProblem } from "../../api/errors";
import { Button, Field, Input, Logo, PanelLoader, cn, focusRing } from "../../components";
import { env } from "../../lib/env";
import { formatUsd, toMicros } from "../../lib/money";
import { SEED_PER_MINUTE_MICROS, talkMinutes } from "../../lib/stack";
import { BILLING_PATH } from "../../lib/paths";

/** The fake gateway's checkout session (services/api/app/dev/router.py). */
interface TestCard {
  number: string;
  brand: string;
  label: string;
  outcome: string;
}
interface CheckoutSessionInfo {
  id: string;
  amount_usd: string;
  status: "pending" | "completed" | "expired";
  workspace_name: string | null;
  cancel_url: string;
  test_cards: TestCard[];
}

/** Dev endpoints are outside the contract, so they go through plain fetch. */
async function devCall<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${env.apiBaseUrl}/dev/fake-checkout/${path}`, { headers: { "content-type": "application/json" }, ...init });
  } catch {
    throw new ApiError(0, toProblem(0, null));
  }
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, toProblem(res.status, body));
  return body as T;
}

const groupCard = (digits: string) => digits.replace(/(\d{4})(?=\d)/g, "$1 ");
const brandOf = (digits: string) =>
  digits.startsWith("4") ? "visa" : /^(5[1-5]|2[2-7])/.test(digits) ? "mastercard" : digits.startsWith("3") ? "amex" : null;
const OK_OUTCOME = "succeeded";

/**
 * Test checkout (STRIPE_MODE=fake): where "Add funds" lands instead of Stripe. Laid out like a
 * hosted checkout, with an order summary and a card form, and plainly marked as test mode. Stripe's
 * test card numbers decide the outcome on the API, so declines, insufficient funds, expired cards
 * and the rest can be tried; a success credits the balance through the same webhook path as Stripe.
 */
export function TestCheckout() {
  const { sessionId = "" } = useParams();
  const session = useQuery({
    queryKey: ["dev", "checkout", sessionId],
    queryFn: () => devCall<CheckoutSessionInfo>(encodeURIComponent(sessionId)),
    retry: false,
  });

  return (
    <div className="min-h-dvh bg-bg">
      <div className="flex justify-center border-b border-line bg-warning-soft px-4 py-2 text-[13px] font-medium text-warning-text">
        <span className="inline-flex items-center gap-2">
          <FlaskConical className="size-4" aria-hidden />
          Test mode. No real card is charged.
        </span>
      </div>
      {session.isPending ? (
        <PanelLoader label="Loading checkout" />
      ) : session.isError ? (
        <Notice icon={<CircleAlert aria-hidden />} tone="danger" title="This checkout link isn't valid" text="Start a new top-up from Billing." />
      ) : session.data.status === "completed" ? (
        <Notice icon={<CircleCheck aria-hidden />} tone="success" title="This top-up is already paid" text="The credit is in your balance." />
      ) : session.data.status === "expired" ? (
        <Notice icon={<CircleAlert aria-hidden />} tone="danger" title="This checkout has expired" text="Start a new top-up from Billing." />
      ) : (
        <Checkout info={session.data} />
      )}
    </div>
  );
}

function Notice({ icon, tone, title, text }: { icon: ReactNode; tone: "danger" | "success"; title: string; text: string }) {
  return (
    <div className="mx-auto flex max-w-md flex-col items-center gap-4 px-4 py-24 text-center">
      <span
        className={cn(
          "grid size-12 place-items-center rounded-full [&_svg]:size-6",
          tone === "danger" ? "bg-danger-soft text-danger-text" : "bg-success-soft text-success-text",
        )}
      >
        {icon}
      </span>
      <h1 className="font-display text-[22px] tracking-[-0.02em] text-fg">{title}</h1>
      <p className="text-[14px] text-fg-2">{text}</p>
      <Button asChild variant="secondary" icon={<ArrowLeft aria-hidden />}>
        <Link to={BILLING_PATH}>Back to Billing</Link>
      </Button>
    </div>
  );
}

interface Form {
  number: string;
  expiry: string;
  cvc: string;
  name: string;
}
type FieldErrors = Partial<Record<keyof Form, string>>;
const POINTERS: Record<string, keyof Form> = {
  "/card_number": "number",
  "/exp_month": "expiry",
  "/exp_year": "expiry",
  "/cvc": "cvc",
  "/name": "name",
};

function Checkout({ info }: { info: CheckoutSessionInfo }) {
  const [form, setForm] = useState<Form>({ number: "", expiry: "", cvc: "", name: "" });
  const [errors, setErrors] = useState<FieldErrors>({});
  const [decline, setDecline] = useState<string | null>(null);
  const [phase, setPhase] = useState<"idle" | "paying" | "paid" | "leaving">("idle");
  const numberRef = useRef<HTMLInputElement>(null);
  const amount = formatUsd(info.amount_usd);
  const micros = toMicros(info.amount_usd) ?? 0n;
  const digits = form.number.replace(/\D/g, "");
  const brand = brandOf(digits);

  const set = (key: keyof Form, value: string) => {
    setForm((f) => ({ ...f, [key]: value }));
    setErrors((e) => ({ ...e, [key]: undefined }));
    setDecline(null);
  };

  const fill = (card: TestCard) => {
    setForm((f) => ({ number: groupCard(card.number), expiry: "12 / 34", cvc: "123", name: f.name || "Ada Lovelace" }));
    setErrors({});
    setDecline(null);
  };

  const pay = async (e: FormEvent) => {
    e.preventDefault();
    const [mm = "", yy = ""] = form.expiry.split("/").map((p) => p.trim());
    const local: FieldErrors = {};
    if (digits.length < 13) local.number = "Your card number is incomplete.";
    if (!/^\d{2}$/.test(mm) || !/^\d{2}$/.test(yy)) local.expiry = "Your card's expiration date is incomplete.";
    if (!/^\d{3,4}$/.test(form.cvc)) local.cvc = "Your card's security code is incomplete.";
    if (!form.name.trim()) local.name = "Enter the name on the card.";
    if (Object.keys(local).length) {
      setErrors(local);
      return;
    }
    setPhase("paying");
    try {
      const done = await devCall<{ redirect_url: string }>(`${encodeURIComponent(info.id)}/pay`, {
        method: "POST",
        body: JSON.stringify({ card_number: digits, exp_month: Number(mm), exp_year: Number(yy), cvc: form.cvc, name: form.name }),
      });
      setPhase("paid");
      setTimeout(() => window.location.assign(done.redirect_url), 1600);
    } catch (err) {
      setPhase("idle");
      const p = err instanceof ApiError ? err.problem : null;
      if (p?.errors?.length) {
        const next: FieldErrors = {};
        for (const fe of p.errors) {
          const key = POINTERS[fe.pointer ?? ""];
          if (key && !next[key]) next[key] = fe.message;
        }
        setErrors(next);
      } else {
        setDecline(p?.detail ?? "The payment didn't go through. Try again.");
        numberRef.current?.focus();
      }
    }
  };

  const cancel = async () => {
    setPhase("leaving");
    const done = await devCall<{ redirect_url: string }>(`${encodeURIComponent(info.id)}/cancel`, { method: "POST" }).catch(() => ({
      redirect_url: info.cancel_url,
    }));
    window.location.assign(done.redirect_url);
  };

  return (
    <div className="mx-auto grid max-w-[1040px] gap-10 px-4 py-10 sm:px-6 md:grid-cols-[minmax(0,0.9fr)_minmax(0,1fr)] md:gap-16 md:py-16">
      <section aria-label="Order summary" className="flex flex-col gap-8">
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => void cancel()}
            disabled={phase !== "idle"}
            aria-label="Cancel and go back to Callwright"
            className={cn(
              "grid size-8 cursor-pointer place-items-center rounded-full text-fg-2 hover:bg-surface-2 hover:text-fg disabled:opacity-50",
              focusRing,
            )}
          >
            <ArrowLeft className="size-4" aria-hidden />
          </button>
          <Logo />
        </div>
        <div>
          <p className="text-[14px] text-fg-2">Add funds to {info.workspace_name ?? "your workspace"}</p>
          <p className="mt-2 font-mono text-[40px] font-semibold leading-none tracking-[-0.02em] text-fg tnum">{amount}</p>
          <p className="mt-3 text-[14px] text-fg-3">
            About <span className="font-mono text-fg-2 tnum">{talkMinutes(micros, SEED_PER_MINUTE_MICROS)}</span> minutes of calls on the default
            stack.
          </p>
        </div>
        <dl className="flex flex-col gap-3 border-t border-line pt-5 text-[14px]">
          <div className="flex justify-between gap-4">
            <dt className="text-fg-2">Call credit</dt>
            <dd className="font-mono text-fg tnum">{formatUsd(micros)}</dd>
          </div>
          <div className="flex justify-between gap-4 border-t border-line pt-3 font-medium">
            <dt className="text-fg">Total due today</dt>
            <dd className="font-mono text-fg tnum">{formatUsd(micros)}</dd>
          </div>
        </dl>
      </section>

      <section aria-label="Payment" className="rounded-feature border border-line bg-surface p-6 shadow-1 sm:p-8">
        <AnimatePresence mode="wait" initial={false}>
          {phase === "paid" ? (
            <motion.div
              key="paid"
              initial={{ opacity: 0, scale: 0.98 }}
              animate={{ opacity: 1, scale: 1 }}
              className="flex min-h-[420px] flex-col items-center justify-center gap-4 text-center"
              role="status"
            >
              <motion.span
                initial={{ scale: 0.4, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                transition={{ type: "spring", stiffness: 380, damping: 20 }}
                className="grid size-14 place-items-center rounded-full bg-success-soft text-success-text"
              >
                <CircleCheck className="size-7" aria-hidden />
              </motion.span>
              <h1 className="font-display text-[22px] tracking-[-0.02em] text-fg">Payment received</h1>
              <p className="text-[14px] text-fg-2">{amount} is on its way to your balance. Taking you back to Billing.</p>
            </motion.div>
          ) : (
            <motion.form key="form" onSubmit={(e) => void pay(e)} noValidate className="flex flex-col gap-5" exit={{ opacity: 0 }}>
              <h1 className="flex items-center gap-2 text-[16px] font-semibold text-fg">
                <CreditCard className="size-[18px] text-fg-3" aria-hidden />
                Pay with card
              </h1>
              <Field label="Card number" error={errors.number}>
                {({ id, describedBy, invalid }) => (
                  <Input
                    ref={numberRef}
                    id={id}
                    aria-describedby={describedBy}
                    aria-invalid={invalid || Boolean(decline)}
                    inputMode="numeric"
                    autoComplete="cc-number"
                    placeholder="1234 1234 1234 1234"
                    inputSize="lg"
                    className="font-mono tnum"
                    value={form.number}
                    onChange={(e) => set("number", groupCard(e.target.value.replace(/\D/g, "").slice(0, 19)))}
                    suffix={brand ? <BrandMark brand={brand} /> : undefined}
                  />
                )}
              </Field>
              <div className="grid grid-cols-2 gap-4">
                <Field label="Expiry" error={errors.expiry}>
                  {({ id, describedBy, invalid }) => (
                    <Input
                      id={id}
                      aria-describedby={describedBy}
                      aria-invalid={invalid}
                      inputMode="numeric"
                      autoComplete="cc-exp"
                      placeholder="MM / YY"
                      inputSize="lg"
                      className="font-mono tnum"
                      value={form.expiry}
                      onChange={(e) => {
                        const d = e.target.value.replace(/\D/g, "").slice(0, 4);
                        set("expiry", d.length > 2 ? `${d.slice(0, 2)} / ${d.slice(2)}` : d);
                      }}
                    />
                  )}
                </Field>
                <Field label="Security code" error={errors.cvc}>
                  {({ id, describedBy, invalid }) => (
                    <Input
                      id={id}
                      aria-describedby={describedBy}
                      aria-invalid={invalid}
                      inputMode="numeric"
                      autoComplete="cc-csc"
                      placeholder="CVC"
                      inputSize="lg"
                      className="font-mono tnum"
                      value={form.cvc}
                      onChange={(e) => set("cvc", e.target.value.replace(/\D/g, "").slice(0, 4))}
                    />
                  )}
                </Field>
              </div>
              <Field label="Name on card" error={errors.name}>
                {({ id, describedBy, invalid }) => (
                  <Input
                    id={id}
                    aria-describedby={describedBy}
                    aria-invalid={invalid}
                    autoComplete="cc-name"
                    placeholder="Full name"
                    inputSize="lg"
                    value={form.name}
                    onChange={(e) => set("name", e.target.value)}
                  />
                )}
              </Field>
              <AnimatePresence initial={false}>
                {decline && (
                  <motion.p
                    role="alert"
                    initial={{ opacity: 0, y: -4 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0 }}
                    className="flex items-start gap-2 rounded-control border border-danger/30 bg-danger-soft px-3 py-2.5 text-[14px] text-danger-text"
                  >
                    <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
                    {decline}
                  </motion.p>
                )}
              </AnimatePresence>
              <Button
                type="submit"
                variant="primary"
                size="lg"
                icon={<Lock aria-hidden />}
                pending={phase === "paying"}
                disabled={phase === "leaving"}
              >
                {phase === "paying" ? "Processing" : `Pay ${amount}`}
              </Button>
              <TestCards cards={info.test_cards} onPick={fill} disabled={phase !== "idle"} />
            </motion.form>
          )}
        </AnimatePresence>
      </section>
    </div>
  );
}

function TestCards({ cards, onPick, disabled }: { cards: TestCard[]; onPick: (c: TestCard) => void; disabled: boolean }) {
  return (
    <div className="flex flex-col gap-2 border-t border-line pt-5">
      <p className="text-[13px] font-medium text-fg">Test cards</p>
      <p className="text-[13px] text-fg-3">Pick one to fill the form. Any future expiry date and any 3 digit code work.</p>
      <ul className="mt-1 flex flex-col">
        {cards.map((c) => {
          const ok = c.outcome === OK_OUTCOME;
          return (
            <li key={c.number}>
              <button
                type="button"
                disabled={disabled}
                aria-label={`${groupCard(c.number)}, ${c.label}`}
                onClick={() => onPick(c)}
                className={cn(
                  "flex w-full cursor-pointer items-center gap-3 rounded-control px-2 py-2 text-left transition-colors hover:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-50",
                  focusRing,
                )}
              >
                <BrandMark brand={c.brand} />
                <span className="whitespace-nowrap font-mono text-[13px] text-fg tnum">
                  <span className="hidden sm:inline">{groupCard(c.number)}</span>
                  <span className="sm:hidden">•••• {c.number.slice(-4)}</span>
                </span>
                <span
                  className={cn(
                    "ml-auto inline-flex items-center gap-1.5 whitespace-nowrap text-[13px]",
                    ok ? "text-success-text" : "text-danger-text",
                  )}
                >
                  <span aria-hidden className={cn("size-1.5 rounded-full", ok ? "bg-success" : "bg-danger")} />
                  {c.label}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function BrandMark({ brand }: { brand: string }) {
  if (brand === "mastercard")
    return (
      <span
        aria-label="Mastercard"
        className="relative inline-flex h-5 w-8 shrink-0 items-center justify-center rounded-[4px] border border-line bg-surface"
      >
        <span className="size-3 rounded-full bg-[#eb001b]" />
        <span className="-ml-1.5 size-3 rounded-full bg-[#f79e1b] opacity-90" />
      </span>
    );
  return (
    <span
      aria-label={brand === "visa" ? "Visa" : brand}
      className="inline-flex h-5 w-8 shrink-0 items-center justify-center rounded-[4px] border border-line bg-surface text-[9px] font-extrabold italic tracking-tight text-accent-text"
    >
      {brand === "visa" ? "VISA" : brand.toUpperCase().slice(0, 4)}
    </span>
  );
}
