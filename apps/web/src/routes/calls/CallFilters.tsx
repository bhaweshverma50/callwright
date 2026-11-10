import * as RP from "@radix-ui/react-popover";
import { Check, ListFilter, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useId, useState, type ComponentProps, type ReactNode } from "react";
import {
  Button,
  CHANNEL_LABELS,
  cn,
  EVAL_LABELS,
  focusRing,
  Input,
  ORIGIN_LABELS,
  REASON_LABELS,
  SENTIMENT_LABELS,
  STATUS_LABELS,
} from "../../components";
import { LABEL_LABELS, emptyFilters, type CallFilters as Filters, type FilterChip, type MultiKey } from "./filters";

function Toggle({ on, onClick, children }: { on: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      aria-pressed={on}
      onClick={onClick}
      className={cn(
        "inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-full border px-3 text-[13px] transition-[background-color,border-color,color,transform] duration-150 active:scale-[0.97]",
        on
          ? "border-accent bg-accent-soft font-medium text-accent-text"
          : "border-line-strong bg-surface text-fg-2 hover:border-accent/50 hover:text-fg",
        focusRing,
      )}
    >
      {on && <Check className="size-3.5" aria-hidden strokeWidth={2.5} />}
      {children}
    </button>
  );
}

function Group({ title, children }: { title: string; children: ReactNode }) {
  const id = useId();
  return (
    <fieldset aria-labelledby={id} className="flex flex-col gap-2">
      <legend id={id} className="text-[12px] font-medium text-fg-3">
        {title}
      </legend>
      <div className="flex flex-wrap gap-1.5">{children}</div>
    </fieldset>
  );
}

/** A text filter that applies after typing pauses (or on Enter), so the list does not refetch per key. */
export function DebouncedInput({
  value,
  onCommit,
  ...rest
}: { value: string; onCommit: (v: string) => void } & Omit<ComponentProps<typeof Input>, "value" | "onChange">) {
  const [draft, setDraft] = useState(value);
  const [synced, setSynced] = useState(value);
  if (value !== synced) {
    setSynced(value);
    setDraft(value);
  }
  useEffect(() => {
    if (draft === value) return;
    const t = window.setTimeout(() => onCommit(draft.trim()), 450);
    return () => window.clearTimeout(t);
  }, [draft, value, onCommit]);
  return (
    <Input
      {...rest}
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onKeyDown={(e) => {
        if (e.key === "Enter") onCommit(draft.trim());
      }}
    />
  );
}

const MULTI: { key: MultiKey; title: string; labels: Record<string, string> }[] = [
  { key: "status", title: "Status", labels: STATUS_LABELS },
  { key: "channel", title: "Channel", labels: CHANNEL_LABELS },
  { key: "disconnect_reason", title: "Ended by", labels: REASON_LABELS },
  { key: "sentiment", title: "Sentiment", labels: SENTIMENT_LABELS },
  { key: "label", title: "Your label", labels: LABEL_LABELS },
  { key: "eval_status", title: "Evaluation", labels: EVAL_LABELS },
  { key: "origin", title: "Origin", labels: ORIGIN_LABELS },
];

/**
 * The filter panel (FR-004): OR inside a group, AND across groups. Every change applies at once;
 * typed values apply when typing pauses.
 */
export function FilterButton({
  filters,
  count,
  agents,
  onChange,
}: {
  filters: Filters;
  count: number;
  agents: { id: string; name: string }[];
  onChange: (f: Filters) => void;
}) {
  const toggle = (key: MultiKey, value: string) => {
    const current = filters[key] as string[];
    const next = current.includes(value) ? current.filter((v) => v !== value) : [...current, value];
    onChange({ ...filters, [key]: next });
  };
  const dateId = useId();
  return (
    <RP.Root>
      <RP.Trigger asChild>
        <Button variant="secondary" icon={<ListFilter aria-hidden />} aria-label={count ? `Filters, ${count} applied` : "Filters"}>
          Filters
          {count > 0 && (
            <span
              className="bg-accent grid h-[18px] min-w-[18px] place-items-center rounded-full px-1 font-mono text-[11px] font-medium text-white tnum"
              aria-hidden
            >
              {count}
            </span>
          )}
        </Button>
      </RP.Trigger>
      <RP.Portal>
        <RP.Content
          align="start"
          sideOffset={8}
          collisionPadding={12}
          className="z-50 flex max-h-[min(640px,var(--radix-popover-content-available-height))] w-[min(600px,calc(100vw-24px))] flex-col overflow-hidden rounded-panel border border-line bg-surface shadow-pop data-[state=open]:animate-pop-in"
        >
          <div className="flex items-center justify-between border-b border-line px-5 py-3">
            <h2 className="text-[14px] font-semibold text-fg">Filter calls</h2>
            <RP.Close asChild>
              <button
                type="button"
                aria-label="Close filters"
                className={cn("grid size-7 cursor-pointer place-items-center rounded-control text-fg-3 hover:bg-surface-3 hover:text-fg", focusRing)}
              >
                <X className="size-4" aria-hidden />
              </button>
            </RP.Close>
          </div>
          <div className="flex flex-col gap-5 overflow-y-auto px-5 py-4">
            {MULTI.slice(0, 4).map((g) => (
              <Group key={g.key} title={g.title}>
                {Object.entries(g.labels).map(([value, label]) => (
                  <Toggle key={value} on={(filters[g.key] as string[]).includes(value)} onClick={() => toggle(g.key, value)}>
                    {label}
                  </Toggle>
                ))}
              </Group>
            ))}
            <Group title="Agent">
              {agents.length === 0 && <span className="text-[13px] text-fg-3">No agents yet.</span>}
              {agents.map((a) => (
                <Toggle key={a.id} on={filters.agent_id.includes(a.id)} onClick={() => toggle("agent_id", a.id)}>
                  {a.name}
                </Toggle>
              ))}
            </Group>
            <div className="grid grid-cols-[minmax(0,1fr)] gap-4 sm:grid-cols-2">
              <label className="flex flex-col gap-1.5">
                <span className="text-[12px] font-medium text-fg-3">From number</span>
                <DebouncedInput
                  inputSize="sm"
                  placeholder="+1 555"
                  inputMode="tel"
                  value={filters.from_number}
                  onCommit={(v) => onChange({ ...filters, from_number: v })}
                />
              </label>
              <label className="flex flex-col gap-1.5">
                <span className="text-[12px] font-medium text-fg-3">To number</span>
                <DebouncedInput
                  inputSize="sm"
                  placeholder="+1 415"
                  inputMode="tel"
                  value={filters.to_number}
                  onCommit={(v) => onChange({ ...filters, to_number: v })}
                />
              </label>
            </div>
            <fieldset className="flex flex-col gap-2" aria-describedby={dateId}>
              <legend className="text-[12px] font-medium text-fg-3">Date range</legend>
              <div className="grid grid-cols-[minmax(0,1fr)] gap-4 sm:grid-cols-2">
                <Input
                  inputSize="sm"
                  type="date"
                  aria-label="Start date"
                  value={filters.start_date}
                  max={filters.end_date || undefined}
                  onChange={(e) => onChange({ ...filters, start_date: e.target.value })}
                />
                <Input
                  inputSize="sm"
                  type="date"
                  aria-label="End date"
                  value={filters.end_date}
                  min={filters.start_date || undefined}
                  onChange={(e) => onChange({ ...filters, end_date: e.target.value })}
                />
              </div>
              <p id={dateId} className="text-[12px] text-fg-3">
                Calendar days in your time zone; the end date is included.
              </p>
            </fieldset>
            {MULTI.slice(4).map((g) => (
              <Group key={g.key} title={g.title}>
                {g.key === "label" && (
                  <Toggle on={filters.label.length === 0} onClick={() => onChange({ ...filters, label: [] })}>
                    Any
                  </Toggle>
                )}
                {Object.entries(g.labels).map(([value, label]) => (
                  <Toggle key={value} on={(filters[g.key] as string[]).includes(value)} onClick={() => toggle(g.key, value)}>
                    {label}
                  </Toggle>
                ))}
              </Group>
            ))}
          </div>
          <div className="flex items-center justify-between gap-3 border-t border-line bg-surface-2/50 px-5 py-3">
            <Button variant="link" size="sm" disabled={count === 0} onClick={() => onChange(emptyFilters())}>
              Clear all
            </Button>
            <RP.Close asChild>
              <Button variant="primary" size="sm">
                Done
              </Button>
            </RP.Close>
          </div>
        </RP.Content>
      </RP.Portal>
    </RP.Root>
  );
}

/** Applied filters as removable chips with "Clear all" (FR-036). */
export function FilterChips({
  chips,
  filters,
  onChange,
  onClear,
}: {
  chips: FilterChip[];
  filters: Filters;
  onChange: (f: Filters) => void;
  onClear: () => void;
}) {
  if (chips.length === 0) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5" aria-label="Applied filters" role="group">
      <AnimatePresence initial={false}>
        {chips.map((c) => (
          <motion.span
            key={c.key}
            layout
            initial={{ opacity: 0, scale: 0.92 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.92 }}
            transition={{ duration: 0.16 }}
            className="inline-flex h-7 max-w-full items-center gap-1 rounded-full border border-accent/30 bg-accent-soft pl-3 pr-1 text-[13px] text-accent-text"
          >
            <span className="truncate">{c.label}</span>
            <button
              type="button"
              aria-label={`Remove filter ${c.label}`}
              onClick={() => onChange(c.remove(filters))}
              className={cn("grid size-5 shrink-0 cursor-pointer place-items-center rounded-full hover:bg-accent/15", focusRing)}
            >
              <X className="size-3" aria-hidden />
            </button>
          </motion.span>
        ))}
      </AnimatePresence>
      <Button variant="link" size="sm" className="ml-1 text-[13px]" onClick={onClear}>
        Clear all
      </Button>
    </div>
  );
}
