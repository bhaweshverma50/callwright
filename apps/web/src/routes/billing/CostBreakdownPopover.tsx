import { X } from "lucide-react";
import { motion } from "motion/react";
import type { Transaction } from "../../api/types";
import { CostBreakdownCard, Drawer, IconButton, MoneyText } from "../../components";

const when = new Intl.DateTimeFormat(undefined, { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

/**
 * Itemised cost for a call-charge row (T072), shown in the inspector pane on wide screens and in
 * a drawer on narrow ones. Escape or the close button returns the inspector to Add funds.
 */
export function BreakdownInspector({ txn, onClose, asDrawer }: { txn: Transaction | null; onClose: () => void; asDrawer: boolean }) {
  if (asDrawer) {
    return (
      <Drawer
        open={Boolean(txn)}
        onOpenChange={(o) => !o && onClose()}
        title="Cost breakdown"
        meta={txn ? when.format(new Date(txn.created_at)) : undefined}
        width="md"
      >
        {txn?.cost_breakdown && <Body txn={txn} />}
      </Drawer>
    );
  }
  if (!txn?.cost_breakdown) return null;
  return (
    <motion.section
      key={txn.id}
      aria-label="Cost breakdown"
      initial={{ opacity: 0, x: 12 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
      className="rounded-panel border border-line bg-surface shadow-1"
      onKeyDown={(e) => e.key === "Escape" && onClose()}
    >
      <header className="flex items-start justify-between gap-3 border-b border-line px-5 py-3.5">
        <div className="flex min-w-0 flex-col gap-0.5">
          <h2 className="text-[14px] font-semibold text-fg">Cost breakdown</h2>
          <p className="text-[12.5px] text-fg-3">{when.format(new Date(txn.created_at))}</p>
        </div>
        <IconButton label="Close breakdown" className="-mr-2 -mt-1" onClick={onClose} autoFocus>
          <X className="size-4" aria-hidden />
        </IconButton>
      </header>
      <div className="p-4">
        <Body txn={txn} />
      </div>
    </motion.section>
  );
}

function Body({ txn }: { txn: Transaction }) {
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-baseline justify-between gap-3 px-1">
        <p className="min-w-0 truncate text-[13.5px] text-fg">{txn.description}</p>
        <MoneyText value={txn.amount_usd} places={3} signed className="text-[13.5px] font-medium text-fg" />
      </div>
      {txn.call_id && <p className="-mt-3 truncate px-1 font-mono text-[11.5px] text-fg-3">{txn.call_id}</p>}
      <CostBreakdownCard breakdown={txn.cost_breakdown!} title="Receipt" />
    </div>
  );
}
