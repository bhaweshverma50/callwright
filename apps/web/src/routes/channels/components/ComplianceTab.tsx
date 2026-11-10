import { CalendarClock, FileUp, Plus, Search, ShieldBan, ShieldCheck, Trash2, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";
import { isApiError } from "../../../api/errors";
import { problemMessage } from "../../../api/problems";
import { Badge, Button, IconButton, Input, Pagination, Panel, Select, Skeleton } from "../../../components";
import { useDebounced } from "../../../lib/useDebounced";
import { useDecisions, useDncEntries, useDncMutations } from "../../../api/channels";
import { CallingHoursEditor } from "./CallingHoursEditor";
import { DncImportDialog, REGIONS } from "./DncImportDialog";
import { timeAgo } from "../../../lib/format";
import { bodyLimits } from "../../../lib/contract.gen";

function DncPanel() {
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const q = useDebounced(search.trim(), 250);
  const list = useDncEntries(q, page);
  const { add, remove } = useDncMutations();
  const [number, setNumber] = useState("");
  const [region, setRegion] = useState("none");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);

  const submit = () => {
    setError(null);
    if (!number.trim()) return setError("Enter a number to block.");
    add.mutate(
      { number: number.trim(), ...(region !== "none" && { default_region: region }), ...(note.trim() && { note: note.trim() }) },
      {
        onSuccess: () => {
          setNumber("");
          setNote("");
        },
        onError: (err) =>
          setError(
            isApiError(err) && err.problem.code === "dnc_entry_exists"
              ? "This number is already on the list."
              : isApiError(err) && err.problem.code === "invalid_number"
                ? "Not a phone number. Add the country code or choose a region."
                : problemMessage(err, "entry"),
          ),
      },
    );
  };

  const items = list.data?.items ?? [];
  return (
    <Panel
      title="Do-not-call list"
      description="Outbound calls to these numbers are blocked before dialling and never charged."
      icon={<ShieldBan />}
      actions={
        <Button size="sm" icon={<FileUp aria-hidden />} onClick={() => setImporting(true)}>
          Import CSV
        </Button>
      }
      bodyClassName="p-0"
    >
      <form
        noValidate
        className="grid gap-2 border-b border-line px-5 py-4 sm:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <Input
          aria-label="Number to block"
          className="font-mono"
          inputMode="tel"
          placeholder="+14155550199"
          value={number}
          onChange={(e) => {
            setNumber(e.target.value);
            setError(null);
          }}
        />
        <Select
          aria-label="Region for national numbers"
          value={region}
          onValueChange={setRegion}
          options={REGIONS.map((r) => (r.value === "none" ? { ...r, label: "Region: none" } : r))}
        />
        <Input
          aria-label="Note"
          maxLength={bodyLimits["POST /dnc-entries"].note.maxLength}
          placeholder="Note (optional)"
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
        <Button type="submit" variant="primary" icon={<Plus aria-hidden />} pending={add.isPending}>
          Block number
        </Button>
        {error && (
          <p role="alert" className="text-[13px] text-danger-text sm:col-span-2">
            {error}
          </p>
        )}
      </form>
      <div className="px-5 pt-4">
        <Input
          inputSize="sm"
          prefix={<Search aria-hidden />}
          placeholder="Search numbers"
          aria-label="Search the do-not-call list"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setPage(1);
          }}
          suffix={
            search ? (
              <IconButton label="Clear search" className="size-6 [&_svg]:size-3.5" onClick={() => setSearch("")}>
                <X aria-hidden />
              </IconButton>
            ) : undefined
          }
        />
      </div>
      <div className="px-5 pb-4 pt-3">
        {list.isPending ? (
          <div className="flex flex-col gap-2">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        ) : items.length === 0 ? (
          <div className="flex flex-col items-center gap-2 rounded-panel border border-dashed border-line px-4 py-8 text-center">
            <ShieldCheck className="size-6 text-fg-3" aria-hidden />
            <p className="text-[13px] text-fg-2">{q ? `No numbers match "${q}".` : "No numbers are blocked yet."}</p>
          </div>
        ) : (
          <ul className={list.isPlaceholderData ? "opacity-60 transition-opacity" : "transition-opacity"}>
            <AnimatePresence initial={false}>
              {items.map((e) => (
                <motion.li
                  key={e.id}
                  layout
                  initial={{ opacity: 0, y: -4 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, height: 0 }}
                  className="group flex items-center gap-3 rounded-control px-2 py-2 transition-colors hover:bg-accent-soft/30"
                >
                  <span className="grid size-8 shrink-0 place-items-center rounded-control bg-danger-soft text-danger-text">
                    <ShieldBan className="size-4" aria-hidden />
                  </span>
                  <div className="flex min-w-0 flex-1 flex-col">
                    <span className="truncate font-mono text-[13px] text-fg">{e.number}</span>
                    <span className="truncate text-[12px] text-fg-3">
                      {e.note || (e.source === "csv_import" ? "Imported from CSV" : "Added by hand")} · {timeAgo(e.created_at)}
                    </span>
                  </div>
                  {e.source === "csv_import" && <Badge className="hidden sm:inline-flex">CSV</Badge>}
                  <IconButton label={`Remove ${e.number}`} onClick={() => remove.mutate(e.id)}>
                    <Trash2 className="size-4" aria-hidden />
                  </IconButton>
                </motion.li>
              ))}
            </AnimatePresence>
          </ul>
        )}
        {list.data && list.data.total_pages > 1 && (
          <Pagination
            className="mt-2 px-0"
            page={page}
            totalPages={list.data.total_pages}
            total={list.data.total}
            pageSize={20}
            noun="numbers"
            onPageChange={setPage}
          />
        )}
      </div>
      <DncImportDialog open={importing} onOpenChange={setImporting} />
    </Panel>
  );
}

function DecisionsPanel() {
  const decisions = useDecisions();
  const items = decisions.data?.items ?? [];
  return (
    <Panel
      title="Recently blocked"
      description="Outbound requests stopped by these rules. None were dialled or charged."
      icon={<CalendarClock />}
      bodyClassName="p-0"
    >
      {decisions.isPending ? (
        <div className="p-5">
          <Skeleton className="h-16 w-full" />
        </div>
      ) : items.length === 0 ? (
        <p className="px-5 py-6 text-[13px] text-fg-3">Nothing blocked yet.</p>
      ) : (
        <ul className="divide-y divide-line">
          {items.map((d) => (
            <li key={d.id} className="flex items-start gap-3 px-5 py-3">
              {d.reason === "dnc_listed" ? (
                <Badge tone="danger" icon={<ShieldBan aria-hidden />}>
                  Do not call
                </Badge>
              ) : (
                <Badge tone="warning" icon={<CalendarClock aria-hidden />}>
                  Outside hours
                </Badge>
              )}
              <div className="flex min-w-0 flex-1 flex-col">
                <span className="truncate font-mono text-[13px] text-fg">{d.to_number}</span>
                <span className="truncate text-[12px] text-fg-3">
                  {d.reason === "outside_calling_hours" && d.recipient_local_time
                    ? `${d.recipient_local_time.slice(11, 16)} local in ${d.recipient_timezones?.[0] ?? "unknown zone"}`
                    : d.reason === "outside_calling_hours"
                      ? "No timezone known for the number"
                      : `On the do-not-call list, from ${d.from_number}`}
                </span>
              </div>
              <span className="shrink-0 text-[12px] text-fg-3">{timeAgo(d.decided_at)}</span>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

/** Outbound compliance (010 T078, FR-034 to FR-038): do-not-call list, calling hours, block log. */
export function ComplianceTab() {
  return (
    <div className="grid grid-cols-[minmax(0,1fr)] items-start gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <DncPanel />
      <div className="flex min-w-0 flex-col gap-5">
        <CallingHoursEditor />
        <DecisionsPanel />
      </div>
    </div>
  );
}
