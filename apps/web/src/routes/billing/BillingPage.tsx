import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router";
import { qk, useBalance } from "../../api/queries";
import { Label, MoneyText, PageHeader, Panel, Skeleton, TabPanel, Tabs, toast } from "../../components";
import { formatUsd, toMicros } from "../../lib/money";
import { FormAlert } from "../public/FormAlert";
import { CHECKOUT_BEFORE_KEY, TopUpCard } from "./TopUpCard";
import { TransactionsTable } from "./TransactionsTable";
import { UsagePanel } from "./UsagePanel";

const POLL_MS = 2_000;
const POLL_FOR_MS = 30_000;

type CheckoutWatch = "idle" | "waiting" | "slow" | "cancelled";

/**
 * Billing (T057): balance, add funds, transactions and usage. Returning from hosted checkout with
 * `?checkout=success` polls every 2 s for up to 30 s until the new credit lands (SC-002), then
 * confirms it without a reload.
 */
export function BillingPage() {
  const [params, setParams] = useSearchParams();
  const qc = useQueryClient();
  const checkoutParam = params.get("checkout");
  const [watch, setWatch] = useState<CheckoutWatch>(checkoutParam === "success" ? "waiting" : checkoutParam === "cancelled" ? "cancelled" : "idle");
  const polling = watch === "waiting";
  const balance = useBalance({ pollMs: polling ? POLL_MS : 60_000 });
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

  return (
    <>
      <PageHeader title="Billing" description="Prepaid credit. Calls and features draw from this balance, billed per second." />

      {watch === "waiting" && <FormAlert tone="info">Payment received. Waiting for confirmation, which usually takes a few seconds.</FormAlert>}
      {watch === "slow" && (
        <FormAlert tone="warning">
          Confirmation is taking longer than usual. Your balance updates on its own once the payment clears; you do not need to pay again.
        </FormAlert>
      )}
      {watch === "cancelled" && <FormAlert tone="info">Checkout was cancelled. Nothing was charged.</FormAlert>}

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <Panel title="Balance" description="Derived from every transaction below.">
          <div className="flex flex-col gap-3">
            {balance.isPending ? (
              <Skeleton className="h-10 w-40" />
            ) : balance.data ? (
              <MoneyText value={balance.data.balance_usd} places={3} className="text-[36px] font-medium leading-none tracking-[-0.02em] text-fg" />
            ) : (
              <span className="text-[13px] text-fg-3">Balance unavailable right now.</span>
            )}
            <dl className="mt-2 grid grid-cols-2 gap-4 border-t border-line pt-4">
              <div className="flex flex-col gap-1">
                <dt>
                  <Label>Ledger entries</Label>
                </dt>
                <dd className="font-mono text-[13px] text-fg tnum">{balance.data?.as_of_seq.toLocaleString() ?? ""}</dd>
              </div>
              <div className="flex flex-col gap-1">
                <dt>
                  <Label>New calls stop at</Label>
                </dt>
                <dd className="font-mono text-[13px] text-fg tnum">$0.000</dd>
              </div>
            </dl>
          </div>
        </Panel>
        <TopUpCard />
      </div>

      <div className="mt-8">
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
            { value: "transactions", label: "Transactions" },
            { value: "usage", label: "Usage" },
          ]}
        >
          <TabPanel value="transactions">
            <TransactionsTable pollMs={polling ? POLL_MS : false} />
          </TabPanel>
          <TabPanel value="usage">
            <UsagePanel />
          </TabPanel>
        </Tabs>
      </div>
    </>
  );
}
