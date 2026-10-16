import { Receipt as ReceiptDuo } from "@phosphor-icons/react";
import { ChevronRight, Gift, PhoneCall, Plus, Scale, Sparkles, Undo2, type LucideIcon } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";
import { problemMessage } from "../../api/problems";
import { useTransactions } from "../../api/queries";
import type { Transaction, TransactionType } from "../../api/types";
import { EmptyState, MoneyText, Pagination, Select, Skeleton, TruncatedText, cn, focusRing, type Tone } from "../../components";
import { FAMILY_LABELS } from "./UsagePanel";
import { formatUsd, toMicros } from "../../lib/money";

export const PAGE_SIZE = 20;

export const TYPE_LABELS: Record<TransactionType, string> = {
  top_up: "Top-up",
  call_charge: "Call",
  feature_charge: "Feature",
  trial_grant: "Trial credit",
  refund: "Refund",
  adjustment: "Adjustment",
};

const TYPE_ICONS: Record<TransactionType, LucideIcon> = {
  top_up: Plus,
  call_charge: PhoneCall,
  feature_charge: Sparkles,
  trial_grant: Gift,
  refund: Undo2,
  adjustment: Scale,
};

const TYPE_TONES: Record<TransactionType, Tone> = {
  top_up: "success",
  call_charge: "neutral",
  feature_charge: "neutral",
  trial_grant: "accent",
  refund: "success",
  adjustment: "warning",
};

const NODE_TONE: Record<Tone, string> = {
  success: "bg-success-soft text-success-text",
  neutral: "bg-surface-3 text-fg-2",
  accent: "bg-accent-soft text-accent-text",
  warning: "bg-warning-soft text-warning-text",
  danger: "bg-danger-soft text-danger-text",
};

const timeFmt = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" });
const dayFmt = new Intl.DateTimeFormat(undefined, { weekday: "short", day: "numeric", month: "short" });

function dayKey(d: Date) {
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
}

/** "Today", "Yesterday" or "Mon 14 Oct" in the viewer's time zone. */
export function dayLabel(d: Date, now = new Date()): string {
  if (dayKey(d) === dayKey(now)) return "Today";
  const y = new Date(now);
  y.setDate(y.getDate() - 1);
  if (dayKey(d) === dayKey(y)) return "Yesterday";
  return dayFmt.format(d);
}

/** Groups newest-first rows by local day, keeping order. */
export function groupByDay(items: Transaction[]): { key: string; date: Date; items: Transaction[]; net: bigint }[] {
  const out: { key: string; date: Date; items: Transaction[]; net: bigint }[] = [];
  for (const t of items) {
    const d = new Date(t.created_at);
    const k = dayKey(d);
    let g = out[out.length - 1];
    if (!g || g.key !== k) {
      g = { key: k, date: d, items: [], net: 0n };
      out.push(g);
    }
    g.items.push(t);
    g.net += toMicros(t.amount_usd) ?? 0n;
  }
  return out;
}

/**
 * Ledger history as a day-grouped timeline (T058, FR-009; docs/DESIGN.md section 6): newest
 * first, 20 per page, filter by type. Call charges open their cost breakdown in the inspector.
 */
export function TransactionsTable({
  pollMs,
  selectedId,
  onSelect,
}: {
  pollMs?: number | false;
  selectedId?: string | null;
  onSelect?: (t: Transaction) => void;
}) {
  const [page, setPage] = useState(1);
  const [type, setType] = useState<TransactionType | "all">("all");
  const q = useTransactions(page, PAGE_SIZE, type === "all" ? undefined : type, pollMs);
  const groups = q.data ? groupByDay(q.data.items) : [];

  return (
    <div className="rounded-panel border border-line bg-surface shadow-1">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-3">
        <p className="text-[13px] text-fg-3" aria-live="polite">
          {q.data ? (
            <>
              <span className="font-mono text-fg-2 tnum">{q.data.total.toLocaleString()}</span> {q.data.total === 1 ? "transaction" : "transactions"},
              newest first
            </>
          ) : (
            "Loading transactions"
          )}
        </p>
        <Select
          aria-label="Filter by type"
          size="sm"
          className="w-[170px]"
          value={type}
          onValueChange={(v) => {
            setType(v as TransactionType | "all");
            setPage(1);
          }}
          options={[{ value: "all", label: "All types" }, ...Object.entries(TYPE_LABELS).map(([value, label]) => ({ value, label }))]}
        />
      </div>

      {q.isError && !q.data ? (
        <EmptyState compact icon={<ReceiptDuo weight="duotone" />} title="Transactions did not load">
          {problemMessage(q.error, "transaction")}
        </EmptyState>
      ) : q.isPending ? (
        <div className="flex flex-col gap-4 px-5 py-5" aria-hidden>
          {Array.from({ length: 6 }, (_, i) => (
            <div key={i} className="flex items-center gap-4">
              <Skeleton className="size-8 rounded-full" />
              <div className="flex flex-1 flex-col gap-2">
                <Skeleton className="h-3.5 w-1/2" />
                <Skeleton className="h-3 w-1/4" />
              </div>
              <Skeleton className="h-3.5 w-16" />
            </div>
          ))}
        </div>
      ) : q.data.items.length === 0 ? (
        <EmptyState
          compact
          icon={<ReceiptDuo weight="duotone" />}
          title={type === "all" ? "No transactions yet" : `No ${TYPE_LABELS[type].toLowerCase()} transactions`}
        >
          Top-ups, call charges and adjustments appear here as they happen.
        </EmptyState>
      ) : (
        <section
          aria-label="Credit transactions, newest first"
          className={cn("px-3 pb-2 pt-1 transition-opacity sm:px-5", q.isPlaceholderData && "opacity-60")}
        >
          <div className="flex items-center justify-end px-2 pt-3 text-[11.5px] font-medium text-fg-3">
            <span className={FIGURES}>
              <span>Amount</span>
              <span>Balance after</span>
              <span aria-hidden />
            </span>
          </div>
          {groups.map((g) => (
            <div key={g.key} className="pt-3">
              <div className="flex items-center justify-between gap-3 border-b border-line px-2 pb-2">
                <h3 className="text-[13px] font-semibold text-fg">{dayLabel(g.date)}</h3>
                <span className={cn(FIGURES, "text-[12px] text-fg-3")}>
                  <span>
                    <span className="sr-only">Net for the day </span>
                    <MoneyText value={g.net} places={3} signed toned className="font-medium" />
                  </span>
                  <span>
                    <span className="sr-only">Balance at the end of the day </span>
                    <MoneyText value={g.items[0]?.balance_after_usd ?? "0"} places={3} />
                  </span>
                  <span aria-hidden />
                </span>
              </div>
              <ul className="relative">
                <span aria-hidden className="absolute bottom-5 left-[25px] top-5 w-px bg-line" />
                <AnimatePresence initial={false}>
                  {g.items.map((t) => (
                    <motion.li
                      key={t.id}
                      layout="position"
                      initial={{ opacity: 0, y: -6 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0 }}
                      transition={{ duration: 0.18 }}
                    >
                      <TimelineRow t={t} selected={selectedId === t.id} onSelect={onSelect} />
                    </motion.li>
                  ))}
                </AnimatePresence>
              </ul>
            </div>
          ))}
        </section>
      )}
      {q.data && q.data.total > 0 && (
        <div className="border-t border-line">
          <Pagination
            page={q.data.page}
            totalPages={q.data.total_pages}
            total={q.data.total}
            pageSize={q.data.page_size}
            onPageChange={setPage}
            noun="transactions"
          />
        </div>
      )}
    </div>
  );
}

/** Amount, balance after and the open-detail slot: the same widths on every row so figures align. */
const FIGURES = "grid shrink-0 grid-cols-[minmax(76px,auto)_minmax(76px,auto)_16px] items-center gap-x-5 text-right";

function TimelineRow({ t, selected, onSelect }: { t: Transaction; selected: boolean; onSelect?: (t: Transaction) => void }) {
  const Icon = TYPE_ICONS[t.type];
  const tone = TYPE_TONES[t.type];
  const ref = t.call_id ?? t.feature_key;
  // A row that opens its breakdown is a button: the button takes focus, the text inside must not.
  const opens = Boolean(t.cost_breakdown && onSelect);
  const body = (
    <>
      <span className={cn("relative z-[1] grid size-8 shrink-0 place-items-center rounded-full ring-4 ring-surface", NODE_TONE[tone])}>
        <Icon className="size-3.5" aria-hidden />
      </span>
      <span className="flex min-w-0 flex-1 flex-col gap-0.5 text-left">
        <TruncatedText className="text-[13.5px] text-fg" title={t.description} focusable={!opens}>
          {rowTitle(t)}
        </TruncatedText>
        <span className="flex min-w-0 items-center gap-2.5 text-[12px] text-fg-3">
          <time dateTime={t.created_at} className="font-mono tnum">
            {timeFmt.format(new Date(t.created_at))}
          </time>
          <span>{TYPE_LABELS[t.type]}</span>
          {ref && (
            <TruncatedText className="hidden font-mono sm:block" focusable={!opens}>
              {ref}
            </TruncatedText>
          )}
        </span>
      </span>
      <span className={FIGURES}>
        <MoneyText
          value={t.amount_usd}
          places={3}
          signed={!isZero(t.amount_usd)}
          toned
          className={cn("text-[13.5px]", isZero(t.amount_usd) ? "text-fg-3" : "font-medium")}
        />
        <span className="text-[12.5px] text-fg-2">
          <span className="sr-only">Balance after </span>
          <MoneyText value={t.balance_after_usd} places={3} />
        </span>
        {t.cost_breakdown ? (
          <ChevronRight className={cn("size-4 text-fg-3 transition-transform", selected && "translate-x-0.5 text-accent-text")} aria-hidden />
        ) : (
          <span aria-hidden />
        )}
      </span>
    </>
  );
  const cls = cn(
    "relative flex w-full items-center gap-3.5 rounded-control px-2 py-2.5 transition-colors duration-150",
    selected ? "bg-accent-soft/60" : "hover:bg-surface-2",
  );
  if (opens && onSelect) {
    return (
      <button
        type="button"
        aria-pressed={selected}
        aria-label={`${t.description}, ${formatUsd(t.amount_usd, { places: 3, signed: true })}. Show cost breakdown`}
        onClick={() => onSelect(t)}
        className={cn(cls, "cursor-pointer", focusRing)}
      >
        {body}
      </button>
    );
  }
  return <div className={cls}>{body}</div>;
}

/** Zero at the precision shown (3 places): fractions of a tenth of a cent read as no charge. */
function isZero(v: string | null | undefined): boolean {
  return v != null && Math.abs(Number(v)) < 0.0005;
}

const FEATURE_PREFIXES: [string, string][] = [
  ["eval.", "Evaluation"],
  ["simulator.", "Simulation"],
  ["issues.", "Issue detection"],
];

function humanize(key: string): string {
  const s = key.replace(/[._]+/g, " ").trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/** What the row is, in words people use; the raw description and ids stay in the meta line. */
export function rowTitle(t: Transaction): string {
  if (t.type === "call_charge") {
    const m = /\((\d+):(\d{2})\)/.exec(t.description ?? "");
    return m ? `Call, ${Number(m[1])} min ${Number(m[2])} s` : "Call";
  }
  if (t.type === "feature_charge" && t.feature_key) {
    const k = t.feature_key;
    const hit = FEATURE_PREFIXES.find(([p]) => k.startsWith(p));
    if (hit) return `${hit[1]}: ${humanize(k.slice(hit[0].length)).toLowerCase()}`;
    return FAMILY_LABELS[k as keyof typeof FAMILY_LABELS] ?? humanize(k);
  }
  return t.description ?? TYPE_LABELS[t.type];
}
