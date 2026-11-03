import * as DM from "@radix-ui/react-dropdown-menu";
import { MagnifyingGlass, PhoneList } from "@phosphor-icons/react";
import { ArrowDown, ArrowUp, ArrowUpDown, Check, Columns3, Download, FlaskConical, Minus, Search, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useCallback, useMemo, useState, type ReactNode } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { downloadCallsCsv, useAgentOptions, useCalls, type CallListItem } from "../../api/calls";
import { isApiError } from "../../api/errors";
import { problemMessage } from "../../api/problems";
import { Button, EmptyState, MenuContent, PageHeader, Pagination, Select, Skeleton, cn, focusRing, toast } from "../../components";
import { useRegisterVoiceActions } from "../../app/copilot/actionRegistry";
import { FormAlert } from "../public/FormAlert";
import { CallDetailDrawer, StatusBadge, type DrawerTab } from "./CallDetailDrawer";
import { CallsTabs } from "./CallsTabs";
import { OnAirStrip } from "./live/LiveCalls";
import { LiveDuration } from "./live/LiveDuration";
import { DebouncedInput, FilterButton, FilterChips } from "./CallFilters";
import { CHANNEL_ICONS, COLUMNS, EXPORT_KEYS, useColumnVisibility, type CallColumn } from "./columns";
import {
  CHANNEL_LABELS,
  PAGE_SIZES,
  STATUS_LABELS,
  emptyFilters,
  filterChips,
  parseListState,
  toApiQuery,
  toSearchParams,
  viewerTimeZone,
  type CallFilters,
  type ListState,
} from "./filters";
import { mss, usd, when } from "./format";
import { MAX_SELECTION, checkSimulation, useCallSelection } from "./selection";
import { AddToDatasetMenu } from "../datasets/AddToDatasetMenu";
import { StartSimulationDialog } from "../simulations/StartSimulationDialog";
import { summaryHeadline } from "./quality/SummaryText";

function Checkbox({ checked, onChange, label, mixed }: { checked: boolean; mixed?: boolean; onChange: () => void; label: string }) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={mixed ? "mixed" : checked}
      aria-label={label}
      onClick={(e) => {
        e.stopPropagation();
        onChange();
      }}
      className={cn(
        "grid size-[18px] cursor-pointer place-items-center rounded-[5px] border transition-[background-color,border-color,transform] duration-150 active:scale-90",
        checked || mixed ? "grad-action border-transparent text-white" : "border-line-strong bg-surface hover:border-accent",
        focusRing,
      )}
    >
      {mixed ? <Minus className="size-3" strokeWidth={3} aria-hidden /> : checked ? <Check className="size-3" strokeWidth={3} aria-hidden /> : null}
    </button>
  );
}

function SortHeader({ column, state, onSort }: { column: CallColumn; state: ListState; onSort: (c: CallColumn) => void }) {
  if (!column.sort) return <>{column.label}</>;
  const active = state.sort === column.sort;
  const Icon = !active ? ArrowUpDown : state.order === "asc" ? ArrowUp : ArrowDown;
  return (
    <button
      type="button"
      onClick={() => onSort(column)}
      className={cn(
        "inline-flex cursor-pointer items-center gap-1 rounded-inline whitespace-nowrap transition-colors hover:text-fg",
        active && "text-fg",
        column.numeric && "flex-row-reverse",
        focusRing,
      )}
      aria-label={`Sort by ${column.label.toLowerCase()}${active ? (state.order === "asc" ? ", ascending" : ", descending") : ""}`}
    >
      {column.label}
      <Icon className={cn("size-3.5", active ? "text-accent-text" : "text-fg-3/70")} aria-hidden />
    </button>
  );
}

function ColumnsMenu({ hidden, toggle }: { hidden: Set<string>; toggle: (k: string) => void }) {
  return (
    <DM.Root>
      <DM.Trigger asChild>
        <Button variant="secondary" icon={<Columns3 aria-hidden />}>
          Columns
        </Button>
      </DM.Trigger>
      <MenuContent className="max-h-[420px] overflow-y-auto">
        <DM.Label className="px-2 pb-1.5 pt-1 text-[12px] text-fg-3">Show columns</DM.Label>
        {COLUMNS.map((c) => (
          <DM.CheckboxItem
            key={c.key}
            checked={c.required || !hidden.has(c.key)}
            disabled={c.required}
            onSelect={(e) => {
              e.preventDefault();
              toggle(c.key);
            }}
            className="flex h-8 cursor-pointer select-none items-center gap-2.5 rounded-[6px] px-2 text-[13px] text-fg outline-none data-[disabled]:cursor-default data-[disabled]:text-fg-3 data-[highlighted]:bg-accent-soft/60"
          >
            <span
              className={cn(
                "grid size-4 place-items-center rounded-[4px] border",
                c.required || !hidden.has(c.key) ? "grad-action border-transparent text-white" : "border-line-strong",
                c.required && "opacity-50",
              )}
              aria-hidden
            >
              <DM.ItemIndicator>
                <Check className="size-3" strokeWidth={3} />
              </DM.ItemIndicator>
            </span>
            {c.label}
            {c.required && <span className="ml-auto text-[11.5px] text-fg-3">Always shown</span>}
          </DM.CheckboxItem>
        ))}
      </MenuContent>
    </DM.Root>
  );
}

function MobileRow({ row, selected, onToggle, onOpen }: { row: CallListItem; selected: boolean; onToggle: () => void; onOpen: () => void }) {
  const Icon = CHANNEL_ICONS[row.channel];
  return (
    <li className={cn("flex gap-3 px-4 py-3.5 transition-colors", selected && "bg-accent-soft/50")}>
      <div className="pt-0.5">
        <Checkbox checked={selected} onChange={onToggle} label={`Select call ${row.call_id}`} />
      </div>
      <button
        type="button"
        onClick={onOpen}
        className={cn("flex min-w-0 flex-1 cursor-pointer flex-col gap-1.5 rounded-inline text-left", focusRing)}
      >
        <span className="flex items-center justify-between gap-2">
          <span className="truncate text-[13.5px] font-medium text-fg">{row.agent.name}</span>
          <StatusBadge status={row.status} />
        </span>
        <span className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12.5px] text-fg-3">
          <span>{when(row.started_at)}</span>
          <span className="flex items-center gap-1">
            <Icon className="size-3.5" aria-hidden />
            {CHANNEL_LABELS[row.channel]}
          </span>
          {row.status === "in_progress" ? (
            <LiveDuration since={row.connected_at} />
          ) : row.status === "ringing" || row.status === "queued" ? (
            <span>Ringing</span>
          ) : (
            <span className="font-mono tnum">{mss(row.duration_s)}</span>
          )}
          <span className="font-mono text-fg-2 tnum">{usd(row.cost_usd ?? null)}</span>
        </span>
        {row.summary && <span className="line-clamp-2 text-[12.5px] text-fg-2">{summaryHeadline(row.summary)}</span>}
      </button>
    </li>
  );
}

function TableSkeleton({ columns }: { columns: number }) {
  return (
    <>
      {Array.from({ length: 8 }, (_, i) => (
        <tr key={i} className="border-b border-line last:border-0">
          <td className="h-12 pl-5">
            <Skeleton className="size-[18px] rounded-[5px]" />
          </td>
          {Array.from({ length: columns }, (_, j) => (
            <td key={j} className="h-12 px-3">
              <Skeleton className={cn("h-3", j % 3 === 0 ? "w-24" : j % 3 === 1 ? "w-16" : "w-20")} />
            </td>
          ))}
        </tr>
      ))}
    </>
  );
}

/**
 * Call History (US1): every call newest first with sort, filters, pagination and the column choice
 * in the address and the browser; calls ticked across pages can start a simulation; any row opens
 * the call drawer at `?call=`.
 */
export function CallHistoryPage() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const { state, dropped } = useMemo(() => parseListState(params), [params]);
  const tz = useMemo(viewerTimeZone, []);
  const apiQuery = useMemo(() => toApiQuery(state, tz), [state, tz]);
  const calls = useCalls(apiQuery);
  const agents = useAgentOptions();
  const { hidden, toggle: toggleColumn, visible } = useColumnVisibility();
  const { selection, toggle, togglePage, clear, limitHit } = useCallSelection();
  const [simError, setSimError] = useState<string | null>(null);
  const [simulating, setSimulating] = useState<{ agentId: string; callIds: string[] } | null>(null);
  const [exporting, setExporting] = useState(false);

  const agentName = useCallback(
    (id: string) => agents.data?.find((a) => a.id === id)?.name ?? calls.data?.items.find((c) => c.agent.id === id)?.agent.name ?? id,
    [agents.data, calls.data],
  );
  const chips = filterChips(state.filters, agentName);

  const update = (next: Partial<ListState>, push = false) => {
    setParams(toSearchParams({ ...state, ...next }, params), { replace: !push });
  };
  const setFilters = (filters: CallFilters) => {
    update({ filters, page: 1 });
    setSimError(null);
  };
  const openCall = (id: string, tab?: DrawerTab) => {
    const p = new URLSearchParams(params);
    p.set("call", id);
    if (tab && tab !== "transcript") p.set("tab", tab);
    else p.delete("tab");
    setParams(p);
  };
  const closeCall = () => {
    const p = new URLSearchParams(params);
    p.delete("call");
    p.delete("tab");
    setParams(p);
  };
  // Voice copilot (T083): "show only failed WhatsApp calls" filters this list in place.
  useRegisterVoiceActions([
    {
      key: "filter_calls",
      label: "Filter calls",
      params_schema: {
        type: "object",
        properties: {
          status: { type: "array", items: { type: "string", enum: Object.keys(STATUS_LABELS) } },
          channel: { type: "array", items: { type: "string", enum: Object.keys(CHANNEL_LABELS) } },
          sentiment: { type: "array", items: { type: "string", enum: ["positive", "neutral", "negative", "unknown"] } },
        },
        additionalProperties: false,
      },
      run: (p) => setFilters({ ...state.filters, ...(p as Partial<CallFilters>) }),
    },
    { key: "export_calls", label: "Export calls", run: () => void exportCsv() },
  ]);
  const callId = params.get("call");
  const tab = (params.get("tab") as DrawerTab | null) ?? "transcript";

  const rows = calls.data?.items;
  const pageRows = (rows ?? []).map((r) => ({ id: r.call_id, agentId: r.agent.id }));
  const pageAll = pageRows.length > 0 && pageRows.every((r) => selection.has(r.id));
  const pageSome = pageRows.some((r) => selection.has(r.id));

  const runSimulation = () => {
    const check = checkSimulation(selection);
    if (!check.ok) {
      setSimError(check.reason);
      return;
    }
    setSimError(null);
    setSimulating({ agentId: check.agentId, callIds: [...selection.keys()] });
  };
  const oneAgent = checkSimulation(selection);

  const exportCsv = async () => {
    setExporting(true);
    try {
      const columns = visible.flatMap((c) => EXPORT_KEYS[c.key] ?? []);
      const name = await downloadCallsCsv(apiQuery, columns);
      toast({ tone: "success", title: "Export downloaded", description: name });
    } catch (e) {
      toast({
        tone: "error",
        title: isApiError(e) && e.problem.code === "export_too_large" ? "Too many calls to export" : "Export failed",
        description: isApiError(e) && e.problem.detail ? e.problem.detail : problemMessage(e, "call"),
      });
    } finally {
      setExporting(false);
    }
  };

  const onSort = (c: CallColumn) => {
    if (!c.sort) return;
    const order = state.sort === c.sort ? (state.order === "desc" ? "asc" : "desc") : "desc";
    update({ sort: c.sort, order, page: 1 });
  };

  const total = calls.data?.total ?? 0;
  const filtered = chips.length > 0;

  let body: ReactNode;
  if (calls.isError && !calls.data) {
    body = (
      <EmptyState
        compact
        icon={<PhoneList weight="duotone" />}
        title="Calls did not load"
        actions={<Button onClick={() => void calls.refetch()}>Try again</Button>}
      >
        {problemMessage(calls.error, "call")}
      </EmptyState>
    );
  } else if (rows && rows.length === 0) {
    body = filtered ? (
      <EmptyState
        compact
        icon={<MagnifyingGlass weight="duotone" />}
        title="No calls match these filters"
        actions={
          <Button variant="secondary" onClick={() => setFilters(emptyFilters())}>
            Clear filters
          </Button>
        }
      >
        Try a wider date range or fewer filters.
      </EmptyState>
    ) : (
      <EmptyState
        compact
        icon={<PhoneList weight="duotone" />}
        title="No calls yet"
        actions={
          <Button variant="primary" onClick={() => navigate("/agents")}>
            Make a test call
          </Button>
        }
      >
        Calls from the agent tester, your phone numbers and the API land here with their transcript, latency and cost.
      </EmptyState>
    );
  }

  return (
    <>
      <PageHeader
        title="Calls"
        description="Every call with its transcript, recording, per-turn latency and itemised cost."
        actions={
          <>
            <ColumnsMenu hidden={hidden} toggle={toggleColumn} />
            <Button variant="secondary" icon={<Download aria-hidden />} onClick={() => void exportCsv()} pending={exporting} disabled={!total}>
              Export CSV
            </Button>
          </>
        }
      />

      <CallsTabs value="history">
        {dropped.length > 0 && (
          <FormAlert tone="info">
            Some filters in the address were not recognised and were ignored: <span className="font-mono">{dropped.join(", ")}</span>.
          </FormAlert>
        )}

        <section aria-label="Call history" className="overflow-hidden rounded-panel border border-line bg-surface shadow-1">
          <div className="flex flex-col gap-3 border-b border-line px-4 py-3 sm:px-5">
            <div className="flex flex-wrap items-center gap-2">
              <DebouncedInput
                inputSize="md"
                prefix={<Search aria-hidden />}
                placeholder="Call ID, 8 characters or more"
                aria-label="Find a call by ID"
                className="w-full sm:w-[280px]"
                value={state.filters.call_id}
                onCommit={(v) => setFilters({ ...state.filters, call_id: v })}
              />
              <FilterButton filters={state.filters} count={chips.length} agents={agents.data ?? []} onChange={setFilters} />
              <p className="ml-auto text-[12.5px] text-fg-3" aria-live="polite">
                {calls.data ? (
                  <>
                    <span className="font-mono text-fg-2 tnum">{total.toLocaleString()}</span> {total === 1 ? "call" : "calls"}
                    {filtered ? " match" : ""}
                  </>
                ) : (
                  <Skeleton className="h-3 w-16" />
                )}
              </p>
            </div>
            {state.filters.call_id && state.filters.call_id.length < 8 && (
              <p className="text-[12px] text-warning-text">Type at least 8 characters of the call ID to search.</p>
            )}
            <FilterChips chips={chips} filters={state.filters} onChange={setFilters} onClear={() => setFilters(emptyFilters())} />
          </div>

          <OnAirStrip onOpen={(id) => openCall(id)} />

          <AnimatePresence initial={false}>
            {selection.size > 0 && (
              <motion.div
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: "auto" }}
                exit={{ opacity: 0, height: 0 }}
                transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
                className="overflow-hidden border-b border-line bg-accent-soft/50"
              >
                <div className="flex flex-wrap items-center gap-3 px-4 py-2.5 sm:px-5">
                  <p className="text-[13px] font-medium text-accent-text" aria-live="polite">
                    <span className="font-mono tnum">{selection.size}</span> selected
                    {limitHit && <span className="ml-2 font-normal text-fg-2">Up to {MAX_SELECTION} calls can be selected.</span>}
                  </p>
                  <div className="ml-auto flex items-center gap-2">
                    <Button
                      variant="ghost"
                      size="sm"
                      icon={<X aria-hidden />}
                      onClick={() => {
                        clear();
                        setSimError(null);
                      }}
                    >
                      Clear
                    </Button>
                    {oneAgent.ok && <AddToDatasetMenu agentId={oneAgent.agentId} callIds={[...selection.keys()]} compact />}
                    <Button variant="primary" size="sm" icon={<FlaskConical aria-hidden />} onClick={runSimulation}>
                      Run simulation
                    </Button>
                  </div>
                </div>
                {simError && (
                  <p role="alert" className="px-5 pb-2.5 text-[12.5px] text-danger-text">
                    {simError}
                  </p>
                )}
              </motion.div>
            )}
          </AnimatePresence>

          {body ?? (
            <>
              <div className="hidden overflow-x-auto md:block">
                <table className="w-full border-collapse text-[13px]">
                  <caption className="sr-only">Calls, newest first</caption>
                  <thead>
                    <tr className="border-b border-line bg-surface-2">
                      <th scope="col" className="sticky left-0 z-[2] h-10 w-12 min-w-12 bg-surface-2 pl-5 pr-2">
                        <Checkbox
                          checked={pageAll}
                          mixed={!pageAll && pageSome}
                          onChange={() => togglePage(pageRows)}
                          label={pageAll ? "Clear this page" : "Select this page"}
                        />
                      </th>
                      {visible.map((c) => (
                        <th
                          key={c.key}
                          scope="col"
                          aria-sort={c.sort && state.sort === c.sort ? (state.order === "asc" ? "ascending" : "descending") : undefined}
                          style={c.width ? { width: c.width } : undefined}
                          className={cn(
                            "h-10 whitespace-nowrap px-3 text-[12px] font-medium text-fg-3 last:pr-5",
                            c.numeric ? "text-right" : "text-left",
                            c.key === "call_id" && "sticky left-12 z-[2] bg-surface-2",
                          )}
                        >
                          <SortHeader column={c} state={state} onSort={onSort} />
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className={cn("transition-opacity duration-200", calls.isPlaceholderData && "opacity-60")}>
                    {!rows ? (
                      <TableSkeleton columns={visible.length} />
                    ) : (
                      rows.map((r, i) => {
                        const ticked = selection.has(r.call_id);
                        const open = callId === r.call_id;
                        return (
                          <motion.tr
                            key={r.call_id}
                            initial={{ opacity: 0, y: 4 }}
                            animate={{ opacity: 1, y: 0 }}
                            transition={{ duration: 0.22, delay: Math.min(i, 20) * 0.012 }}
                            onClick={() => openCall(r.call_id)}
                            aria-selected={open}
                            className={cn(
                              "group cursor-pointer border-b border-line last:border-0",
                              "[--row:var(--surface)] hover:[--row:color-mix(in_srgb,var(--accent-soft)_45%,var(--surface))]",
                              ticked && "[--row:color-mix(in_srgb,var(--accent-soft)_60%,var(--surface))]",
                              open && "[--row:color-mix(in_srgb,var(--accent-soft)_90%,var(--surface))] hover:[--row:var(--accent-soft)]",
                            )}
                          >
                            <td className="sticky left-0 z-[1] h-12 w-12 min-w-12 bg-[var(--row)] pl-5 pr-2 align-middle transition-colors duration-150">
                              <Checkbox checked={ticked} onChange={() => toggle(r.call_id, r.agent.id)} label={`Select call ${r.call_id}`} />
                            </td>
                            {visible.map((c) => (
                              <td
                                key={c.key}
                                className={cn(
                                  "h-12 bg-[var(--row)] px-3 align-middle text-fg transition-colors duration-150 last:pr-5",
                                  c.numeric && "text-right font-mono text-[12.5px] tnum",
                                  c.key === "call_id" && "sticky left-12 z-[1]",
                                )}
                              >
                                {c.cell(r, { open: openCall })}
                              </td>
                            ))}
                          </motion.tr>
                        );
                      })
                    )}
                  </tbody>
                </table>
              </div>
              <ul className="divide-y divide-line md:hidden" aria-label="Calls">
                {!rows
                  ? Array.from({ length: 6 }, (_, i) => (
                      <li key={i} className="flex flex-col gap-2 px-4 py-4">
                        <Skeleton className="h-3.5 w-1/2" />
                        <Skeleton className="h-3 w-3/4" />
                      </li>
                    ))
                  : rows.map((r) => (
                      <MobileRow
                        key={r.call_id}
                        row={r}
                        selected={selection.has(r.call_id)}
                        onToggle={() => toggle(r.call_id, r.agent.id)}
                        onOpen={() => openCall(r.call_id)}
                      />
                    ))}
              </ul>
            </>
          )}

          {calls.data && total > 0 && (
            <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line">
              <Pagination
                page={state.page}
                totalPages={calls.data.total_pages}
                total={total}
                pageSize={state.pageSize}
                noun={total === 1 ? "call" : "calls"}
                onPageChange={(page) => update({ page }, true)}
                className="flex-1"
              />
              <label className="flex items-center gap-2 px-5 pb-3 text-[12.5px] text-fg-3 sm:pb-0">
                Rows per page
                <Select
                  size="sm"
                  aria-label="Rows per page"
                  className="w-[76px]"
                  value={String(state.pageSize)}
                  onValueChange={(v) => update({ pageSize: Number(v), page: 1 })}
                  options={PAGE_SIZES.map((n) => ({ value: String(n), label: String(n) }))}
                />
              </label>
            </div>
          )}
        </section>
      </CallsTabs>

      {simulating && (
        <StartSimulationDialog
          open
          onOpenChange={(o) => !o && setSimulating(null)}
          agentId={simulating.agentId}
          agentName={agentName(simulating.agentId)}
          baseCallIds={simulating.callIds}
        />
      )}

      <CallDetailDrawer
        callId={callId}
        tab={tab}
        onTab={(t) => {
          const p = new URLSearchParams(params);
          if (t === "transcript") p.delete("tab");
          else p.set("tab", t);
          setParams(p, { replace: true });
        }}
        onClose={closeCall}
      />
    </>
  );
}
