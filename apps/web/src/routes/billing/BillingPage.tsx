import { useQueryClient } from "@tanstack/react-query";
import { ChartColumn, History, Plus } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router";
import { qk, useBalance, useQuote } from "../../api/queries";
import type { Transaction } from "../../api/types";
import { Button, FormAlert, PageHeader, TabPanel, Tabs, toast, WorkLayout } from "../../components";
import { formatUsd, toMicros } from "../../lib/money";
import { DEFAULT_STACK } from "../../lib/stack";
import { WIDE, useMediaQuery } from "../../lib/useMediaQuery";
import { BreakdownInspector } from "./CostBreakdownPopover";
import { TalkTimeGauge } from "./TalkTimeGauge";
import { CHECKOUT_BEFORE_KEY, TopUpCard } from "./TopUpCard";
import { TransactionsTable } from "./TransactionsTable";
import { UsagePanel } from "./UsagePanel";

const POLL_MS = 2_000;
const POLL_FOR_MS = 30_000;

type CheckoutWatch = "idle" | "waiting" | "slow" | "cancelled";

/**
 * Billing (T057): balance as talk time, add funds, the transaction timeline and usage. Returning
 * from hosted checkout with `?checkout=success` polls every 2 s for up to 30 s until the new credit
 * lands (SC-002), then confirms it without a reload. A call charge opens its breakdown in the
 * inspector pane (a drawer on narrow screens).
 */
export function BillingPage() {
  const [params, setParams] = useSearchParams();
  const qc = useQueryClient();
  const wide = useMediaQuery(WIDE);
  const checkoutParam = params.get("checkout");
  const [watch, setWatch] = useState<CheckoutWatch>(
    checkoutParam === "success" ? "waiting" : checkoutParam === "cancelled" || checkoutParam === "canceled" ? "cancelled" : "idle",
  );
  const [selected, setSelected] = useState<Transaction | null>(null);
  const amountRef = useRef<HTMLInputElement>(null);
  const polling = watch === "waiting";
  const balance = useBalance({ pollMs: polling ? POLL_MS : 60_000 });
  const stack = useQuote({ components: DEFAULT_STACK });
  const perMinute = stack.data ? toMicros(stack.data.per_minute_total_usd) : null;
  const startBalance = useRef<bigint | null>(null);
  if (polling && startBalance.current === null) {
    try {
      const stored = sessionStorage.getItem(CHECKOUT_BEFORE_KEY);
      if (stored) startBalance.current = toMicros(stored);
    } catch {
      /* storage blocked */
    }
  }
  const tab = params.get("tab") === "usage" ? "usage" : "transactions";

  useEffect(() => {
    if (!polling) return;
    const t = window.setTimeout(() => setWatch("slow"), POLL_FOR_MS);
    return () => window.clearTimeout(t);
  }, [polling]);

  useEffect(() => {
    if (!polling || !balance.data) return;
    const now = toMicros(balance.data.balance_usd) ?? 0n;
    if (startBalance.current === null) {
      startBalance.current = now;
      return;
    }
    if (now > startBalance.current) {
      setWatch("idle");
      try {
        sessionStorage.removeItem(CHECKOUT_BEFORE_KEY);
      } catch {
        /* nothing to clear */
      }
      void qc.invalidateQueries({ queryKey: qk.transactionsAll });
      void qc.invalidateQueries({ queryKey: qk.me });
      toast({ tone: "success", title: "Funds added", description: `${formatUsd(now - startBalance.current, { places: 2 })} is in your balance.` });
      setParams(
        (p) => {
          p.delete("checkout");
          return p;
        },
        { replace: true },
      );
    }
  }, [polling, balance.data, qc, setParams]);

  const focusAmount = () => {
    setSelected(null);
    window.setTimeout(() => {
      amountRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
      amountRef.current?.focus({ preventScroll: true });
    }, 0);
  };

  const topUp = <TopUpCard inputRef={amountRef} perMinuteMicros={perMinute} />;
  const inspectorBreakdown = wide && selected ? <BreakdownInspector txn={selected} onClose={() => setSelected(null)} asDrawer={false} /> : null;

  return (
    <>
      <PageHeader
        title="Billing"
        description="Prepaid credit for calls and features, billed per second."
        actions={
          <Button variant="primary" icon={<Plus aria-hidden />} onClick={focusAmount}>
            Add funds
          </Button>
        }
      />

      {watch === "waiting" && <FormAlert tone="info">Payment received. Waiting for confirmation, which usually takes a few seconds.</FormAlert>}
      {watch === "slow" && (
        <FormAlert tone="warning">
          Confirmation is taking longer than usual. Your balance updates on its own once the payment clears; you do not need to pay again.
        </FormAlert>
      )}
      {watch === "cancelled" && <FormAlert tone="info">Checkout was cancelled. Nothing was charged.</FormAlert>}

      <WorkLayout
        main={
          <div className="flex flex-col gap-8">
            <TalkTimeGauge balanceUsd={balance.data?.balance_usd} loading={balance.isPending} />
            {!wide && topUp}
            <Tabs
              aria-label="Billing history"
              value={tab}
              onValueChange={(v) =>
                setParams(
                  (p) => {
                    if (v === "usage") p.set("tab", "usage");
                    else p.delete("tab");
                    return p;
                  },
                  { replace: true },
                )
              }
              items={[
                { value: "transactions", label: "Transactions", icon: <History aria-hidden /> },
                { value: "usage", label: "Usage", icon: <ChartColumn aria-hidden /> },
              ]}
            >
              <TabPanel value="transactions">
                <TransactionsTable
                  pollMs={polling ? POLL_MS : false}
                  selectedId={selected?.id ?? null}
                  onSelect={(t) => setSelected((s) => (s?.id === t.id ? null : t))}
                />
              </TabPanel>
              <TabPanel value="usage">
                <UsagePanel />
              </TabPanel>
            </Tabs>
          </div>
        }
        inspector={wide ? (inspectorBreakdown ?? topUp) : null}
      />
      {!wide && <BreakdownInspector txn={selected} onClose={() => setSelected(null)} asDrawer />}
    </>
  );
}
