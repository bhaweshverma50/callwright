import { MagnifyingGlass, PhoneOutgoing } from "@phosphor-icons/react";
import { CalendarX, PhoneCall, PhoneForwarded } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router";
import { useCallbacks, type Callback, type CallbackStatus } from "../../../api/callbacks";
import { problemMessage } from "../../../api/problems";
import {
  Button,
  DEFAULT_LIST_PAGE_SIZE,
  EmptyState,
  PageHeader,
  PagerCompact,
  Pagination,
  Segmented,
  Select,
  Skeleton,
  Table,
  TruncatedText,
  usePageSize,
  type Column,
} from "../../../components";
import { CallDetailDrawer, type DrawerTab } from "../CallDetailDrawer";
import { CallsTabs } from "../CallsTabs";
import { CallbackStatusBadge, CallbackTime, CancelCallbackDialog } from "./CallbackParts";
import { CALLBACK_STATUS_LABELS, callDrawerSearch, dayLabel, failureShort, failureText, phoneLabel } from "./format";

type Filter = "all" | Extract<CallbackStatus, "scheduled" | "placed" | "failed" | "cancelled">;
const FILTERS: Filter[] = ["all", "scheduled", "placed", "failed", "cancelled"];

const linkClass = "inline-flex items-center gap-1.5 whitespace-nowrap rounded-inline text-[13px] font-medium text-accent-text hover:underline";

function SourceLink({ cb, params }: { cb: Callback; params: URLSearchParams }) {
  if (cb.source_call_id)
    return (
      <Link to={callDrawerSearch(params, cb.source_call_id)} className={linkClass} aria-label={`Open the call this callback was booked on`}>
        <PhoneCall className="size-3.5" aria-hidden />
        During a call
      </Link>
    );
  return <span className="whitespace-nowrap text-[13px] text-fg-3">{cb.created_via === "api" ? "Through the API" : "By the agent"}</span>;
}

function Outcome({ cb, params, onCancel }: { cb: Callback; params: URLSearchParams; onCancel: (cb: Callback) => void }) {
  switch (cb.status) {
    case "scheduled":
      return (
        <Button
          size="sm"
          variant="ghost"
          icon={<CalendarX aria-hidden />}
          onClick={() => onCancel(cb)}
          aria-label={`Cancel the callback to ${phoneLabel(cb.to_number)}`}
        >
          Cancel
        </Button>
      );
    case "placing":
      return <span className="whitespace-nowrap text-[13px] text-fg-3">Dialling now</span>;
    case "placed":
      return cb.call_id ? (
        <Link to={callDrawerSearch(params, cb.call_id)} className={linkClass} aria-label={`Open the callback call to ${phoneLabel(cb.to_number)}`}>
          <PhoneForwarded className="size-3.5" aria-hidden />
          Open call
        </Link>
      ) : (
        <span className="text-[13px] text-fg-3">Placed</span>
      );
    case "failed":
      return (
        <span title={failureText(cb)} className="whitespace-nowrap text-[13px] text-danger-text">
          {failureShort(cb)}
        </span>
      );
    case "cancelled":
      return (
        <span className="whitespace-nowrap text-[13px] text-fg-3">{cb.cancelled_at ? `Cancelled ${dayLabel(cb.cancelled_at)}` : "Cancelled"}</span>
      );
  }
}

function columns(params: URLSearchParams, onCancel: (cb: Callback) => void): Column<Callback>[] {
  return [
    { key: "when", header: "Scheduled for", cell: (cb) => <CallbackTime callback={cb} nowrap className="font-medium text-fg" /> },
    { key: "status", header: "Status", cell: (cb) => <CallbackStatusBadge status={cb.status} /> },
    {
      key: "to",
      header: "To",
      cell: (cb) => (
        <span className="flex flex-col gap-0.5 py-1.5">
          <span className="whitespace-nowrap font-mono text-[13px] text-fg tnum">{phoneLabel(cb.to_number)}</span>
          <TruncatedText className="max-w-[18ch] text-[12px] text-fg-3">{cb.agent_name ?? "Outbound agent"}</TruncatedText>
        </span>
      ),
    },
    {
      key: "note",
      header: "Note",
      cell: (cb) =>
        cb.note ? (
          <TruncatedText className="max-w-[24ch] text-fg-2 xl:max-w-[34ch] 2xl:max-w-[48ch]">{cb.note}</TruncatedText>
        ) : (
          <span className="text-fg-3">No note</span>
        ),
    },
    { key: "booked", header: "Booked", cell: (cb) => <SourceLink cb={cb} params={params} /> },
    { key: "result", header: "Result", align: "right", cell: (cb) => <Outcome cb={cb} params={params} onCancel={onCancel} /> },
  ];
}

function MobileRow({ cb, params, onCancel }: { cb: Callback; params: URLSearchParams; onCancel: (cb: Callback) => void }) {
  return (
    <li className="flex flex-col gap-2 px-4 py-3.5">
      <div className="flex items-start justify-between gap-3">
        <CallbackTime callback={cb} className="text-[14px] font-medium text-fg" />
        <CallbackStatusBadge status={cb.status} />
      </div>
      <p className="flex min-w-0 flex-wrap items-center gap-x-2 text-[13px] text-fg-3">
        <span className="whitespace-nowrap font-mono text-fg-2 tnum">{phoneLabel(cb.to_number)}</span>
        <span aria-hidden className="text-fg-3/60">
          /
        </span>
        <span className="truncate">{cb.agent_name ?? "Outbound agent"}</span>
      </p>
      {cb.note && <p className="line-clamp-2 text-[13px] leading-relaxed text-fg-2">{cb.note}</p>}
      {cb.status === "failed" && <p className="text-[13px] text-danger-text">{failureText(cb)}</p>}
      <div className="flex min-h-8 flex-wrap items-center gap-x-4 gap-y-2">
        <SourceLink cb={cb} params={params} />
        {cb.status === "placed" && cb.call_id && <Outcome cb={cb} params={params} onCancel={onCancel} />}
        {cb.status === "scheduled" && (
          <span className="ml-auto">
            <Outcome cb={cb} params={params} onCancel={onCancel} />
          </span>
        )}
      </div>
    </li>
  );
}

/**
 * Callbacks (spec 011): outbound calls booked for later, by an agent when a caller asks to be
 * called back or by the API. Filtered by status in the address; times show in the recipient's
 * zone; source and resulting calls open the call drawer here; scheduled ones can be cancelled.
 */
export function CallbacksPage() {
  const [params, setParams] = useSearchParams();
  const raw = params.get("status");
  const filter: Filter = FILTERS.includes(raw as Filter) ? (raw as Filter) : "all";
  const page = Math.max(1, Number(params.get("page") ?? 1) || 1);
  const [pageSize, setPageSize] = usePageSize("callbacks");
  const callbacks = useCallbacks(filter === "all" ? null : filter, page, pageSize);
  const [cancelling, setCancelling] = useState<Callback | null>(null);

  const set = (patch: Record<string, string | null>, replace = true) => {
    const p = new URLSearchParams(params);
    for (const [k, v] of Object.entries(patch)) {
      if (v === null) p.delete(k);
      else p.set(k, v);
    }
    setParams(p, { replace });
  };

  const callId = params.get("call");
  const tab = (params.get("tab") as DrawerTab | null) ?? "transcript";
  const rows = callbacks.data?.items;
  const total = callbacks.data?.total ?? 0;
  const filterLabel = filter === "all" ? "" : CALLBACK_STATUS_LABELS[filter].toLowerCase();

  let body: ReactNode;
  if (callbacks.isError && !callbacks.data) {
    body = (
      <EmptyState
        compact
        icon={<PhoneOutgoing weight="duotone" />}
        title="Callbacks did not load"
        actions={<Button onClick={() => void callbacks.refetch()}>Try again</Button>}
      >
        {problemMessage(callbacks.error, "callback")}
      </EmptyState>
    );
  } else if (rows && rows.length === 0) {
    body =
      filter !== "all" ? (
        <EmptyState
          compact
          icon={<MagnifyingGlass weight="duotone" />}
          title={`No ${filterLabel} callbacks`}
          actions={
            <Button variant="secondary" onClick={() => set({ status: null, page: null })}>
              Show all callbacks
            </Button>
          }
        >
          Nothing has this status right now.
        </EmptyState>
      ) : (
        <EmptyState compact icon={<PhoneOutgoing weight="duotone" />} title="No callbacks yet">
          Callbacks are booked by your agents during phone calls, when a caller asks to be called back later, or by your own systems through the API.
          Each one is placed from the same number at the agreed time, within your calling hours.
        </EmptyState>
      );
  }

  const cols = columns(params, setCancelling);
  const filterOptions = FILTERS.map((f) => ({ value: f, label: f === "all" ? "All callbacks" : CALLBACK_STATUS_LABELS[f] }));

  return (
    <>
      <PageHeader title="Calls" description="Every call with its transcript, recording, per-turn latency and itemised cost." />
      <CallsTabs value="callbacks">
        <section aria-label="Callbacks" className="overflow-hidden rounded-panel border border-line bg-surface shadow-1">
          <div className="flex flex-wrap items-center gap-3 border-b border-line px-4 py-3 sm:px-5">
            <Segmented
              size="sm"
              aria-label="Status"
              className="hidden sm:inline-flex"
              value={filter}
              onValueChange={(v) => set({ status: v === "all" ? null : v, page: null })}
              options={filterOptions.map((o) => (o.value === "all" ? { ...o, label: "All" } : o))}
            />
            <Select
              size="sm"
              aria-label="Status"
              className="w-[160px] sm:hidden"
              value={filter}
              onValueChange={(v) => set({ status: v === "all" ? null : v, page: null })}
              options={filterOptions}
            />
            <div className="ml-auto flex flex-wrap items-center gap-3">
              <p className="text-[13px] text-fg-3" aria-live="polite">
                {callbacks.data ? (
                  <>
                    <span className="font-mono text-fg-2 tnum">{total.toLocaleString()}</span> {filterLabel ? `${filterLabel} ` : ""}
                    {total === 1 ? "callback" : "callbacks"}
                  </>
                ) : (
                  <Skeleton className="h-3 w-16" />
                )}
              </p>
              {callbacks.data && (
                <PagerCompact
                  page={page}
                  totalPages={callbacks.data.total_pages}
                  total={total}
                  pageSize={pageSize}
                  onPageChange={(p) => set({ page: p === 1 ? null : String(p) }, false)}
                />
              )}
            </div>
          </div>

          {body ?? (
            <>
              <Table
                className="hidden md:block"
                caption={filter === "scheduled" ? "Callbacks, soonest first" : "Callbacks, latest scheduled time first"}
                columns={cols}
                rows={rows}
                rowKey={(cb) => cb.id}
                loading={callbacks.isPending}
                stale={callbacks.isPlaceholderData}
                skeletonRows={6}
                selectedKey={callId ? (rows?.find((r) => r.source_call_id === callId || r.call_id === callId)?.id ?? null) : undefined}
              />
              <ul className="divide-y divide-line md:hidden" aria-label="Callbacks">
                {!rows
                  ? Array.from({ length: 5 }, (_, i) => (
                      <li key={i} className="flex flex-col gap-2 px-4 py-4">
                        <Skeleton className="h-3.5 w-1/2" />
                        <Skeleton className="h-3 w-3/4" />
                      </li>
                    ))
                  : rows.map((cb) => <MobileRow key={cb.id} cb={cb} params={params} onCancel={setCancelling} />)}
              </ul>
            </>
          )}

          {callbacks.data && total > DEFAULT_LIST_PAGE_SIZE && (
            <div className="border-t border-line">
              <Pagination
                page={page}
                totalPages={callbacks.data.total_pages}
                total={total}
                pageSize={pageSize}
                noun="callbacks"
                onPageChange={(p) => set({ page: p === 1 ? null : String(p) }, false)}
                onPageSizeChange={(n) => {
                  setPageSize(n);
                  set({ page: null }, false);
                }}
              />
            </div>
          )}
        </section>
      </CallsTabs>

      <CancelCallbackDialog callback={cancelling} onClose={() => setCancelling(null)} />

      <CallDetailDrawer
        callId={callId}
        tab={tab}
        onTab={(t) => set({ tab: t === "transcript" ? null : t })}
        onClose={() => set({ call: null, tab: null }, false)}
      />
    </>
  );
}
