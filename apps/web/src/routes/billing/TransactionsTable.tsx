import { Receipt } from "@phosphor-icons/react";
import { useState } from "react";
import { problemMessage } from "../../api/problems";
import { useTransactions } from "../../api/queries";
import type { Transaction, TransactionType } from "../../api/types";
import { Badge, EmptyState, MoneyText, Pagination, Select, Table, type Column, type Tone } from "../../components";
import { CostBreakdownPopover } from "./CostBreakdownPopover";

export const PAGE_SIZE = 20;

export const TYPE_LABELS: Record<TransactionType, string> = {
  top_up: "Top-up",
  call_charge: "Call",
  feature_charge: "Feature",
  trial_grant: "Trial credit",
  refund: "Refund",
  adjustment: "Adjustment",
};
const TYPE_TONES: Record<TransactionType, Tone> = {
  top_up: "success",
  call_charge: "neutral",
  feature_charge: "neutral",
  trial_grant: "accent",
  refund: "success",
  adjustment: "amber",
};

const dateFmt = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });

const columns: Column<Transaction>[] = [
  {
    key: "date",
    header: "Date",
    width: "150px",
    cell: (t) => (
      <time dateTime={t.created_at} className="whitespace-nowrap font-mono text-[12px] text-fg-2 tnum">
        {dateFmt.format(new Date(t.created_at))}
      </time>
    ),
  },
  { key: "type", header: "Type", width: "120px", cell: (t) => <Badge tone={TYPE_TONES[t.type]}>{TYPE_LABELS[t.type]}</Badge> },
  {
    key: "description",
    header: "Description",
    cell: (t) => (
      <span className="flex min-w-0 flex-col">
        <span className="truncate">{t.description}</span>
        {(t.call_id || t.feature_key) && (
          <span className="truncate font-mono text-[11px] text-fg-3" title={t.call_id ?? t.feature_key ?? undefined}>
            {t.call_id ?? t.feature_key}
          </span>
        )}
      </span>
    ),
  },
  {
    key: "breakdown",
    header: <span className="sr-only">Cost breakdown</span>,
    width: "110px",
    hideOnNarrow: true,
    cell: (t) => (t.cost_breakdown ? <CostBreakdownPopover breakdown={t.cost_breakdown} /> : null),
  },
  { key: "amount", header: "Amount", numeric: true, width: "120px", cell: (t) => <MoneyText value={t.amount_usd} places={3} signed toned /> },
  {
    key: "after",
    header: "Balance after",
    numeric: true,
    width: "130px",
    hideOnNarrow: true,
    cell: (t) => <MoneyText value={t.balance_after_usd} places={3} className="text-fg-2" />,
  },
];

/** Ledger history (T058, FR-009): newest first, 20 per page, filter by type. */
export function TransactionsTable({ pollMs }: { pollMs?: number | false }) {
  const [page, setPage] = useState(1);
  const [type, setType] = useState<TransactionType | "all">("all");
  const q = useTransactions(page, PAGE_SIZE, type === "all" ? undefined : type, pollMs);

  return (
    <div className="rounded-panel border border-line bg-surface shadow-panel">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-2.5">
        <p className="font-mono text-[11.5px] text-fg-3 tnum" aria-live="polite">
          {q.data ? `${q.data.total.toLocaleString()} ${q.data.total === 1 ? "transaction" : "transactions"}, newest first` : "Loading transactions"}
        </p>
        <Select
          aria-label="Filter by type"
          size="sm"
          className="w-[160px]"
          value={type}
          onValueChange={(v) => {
            setType(v as TransactionType | "all");
            setPage(1);
          }}
          options={[{ value: "all", label: "All types" }, ...Object.entries(TYPE_LABELS).map(([value, label]) => ({ value, label }))]}
        />
      </div>
      {q.isError && !q.data ? (
        <EmptyState compact icon={<Receipt />} title="Transactions did not load">
          {problemMessage(q.error, "transaction")}
        </EmptyState>
      ) : (
        <Table
          caption="Credit transactions, newest first"
          columns={columns}
          rows={q.data?.items}
          rowKey={(t) => t.id}
          loading={q.isPending}
          stale={q.isPlaceholderData}
          empty={
            <EmptyState compact icon={<Receipt />} title={type === "all" ? "No transactions yet" : `No ${TYPE_LABELS[type].toLowerCase()} transactions`}>
              Top-ups, call charges and adjustments appear here as they happen.
            </EmptyState>
          }
        />
      )}
      {q.data && q.data.total > 0 && (
        <div className="border-t border-line">
          <Pagination page={q.data.page} totalPages={q.data.total_pages} total={q.data.total} pageSize={q.data.page_size} onPageChange={setPage} noun="transactions" />
        </div>
      )}
    </div>
  );
}
