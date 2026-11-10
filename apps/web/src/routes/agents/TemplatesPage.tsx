import { FlowArrow, MagnifyingGlass, Phone } from "@phosphor-icons/react";
import { ChevronLeft, GitBranch, MessageSquareText, PhoneIncoming, PhoneOutgoing, Plus, Search, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router";
import {
  useTemplateCategories,
  useTemplates,
  type TemplateAgentType,
  type TemplateCategory,
  type TemplateDirection,
  type TemplateSummary,
} from "../../api/agents";
import { problemMessage } from "../../api/problems";
import { Badge, Button, Chip, EmptyState, IconButton, Input, PageHeader, Segmented, Skeleton, cn } from "../../components";
import { useDebounced } from "../../lib/useDebounced";
import { CATEGORY_ICONS, CATEGORY_TINT, TEMPLATE_ICONS } from "./templateIcons";
import { TemplatePreviewDialog } from "./TemplatePreviewDialog";
import { NEW_AGENT_PATH, NEW_FLOW_AGENT_PATH, NEW_SINGLE_AGENT_PATH } from "../../lib/paths";

const DIRECTIONS: readonly TemplateDirection[] = ["inbound", "outbound"];
const TYPES: readonly TemplateAgentType[] = ["single_prompt", "flow"];
const CATEGORIES = Object.keys(CATEGORY_ICONS) as TemplateCategory[];

const humanize = (id: string) => id.charAt(0).toUpperCase() + id.slice(1).replace(/_/g, " ");

const TITLES: Record<TemplateAgentType | "all", { title: string; description: string }> = {
  all: {
    title: "Start from a template",
    description: "Begin from a blank agent, or from a template written for your industry and adjust it. Filter by call direction and agent type.",
  },
  single_prompt: {
    title: "Start a single-prompt agent",
    description: "Begin from a blank agent, or from a template written for your industry and adjust it.",
  },
  flow: {
    title: "Start a flow agent",
    description: "Begin from a blank canvas, or from a ready-made flow of steps and branches and adjust it.",
  },
};

/** Reads one filter from the URL; anything unknown counts as unset so a bad link still loads. */
function pick<T extends string>(raw: string | null, allowed: readonly T[]): T | null {
  return allowed.find((a) => a === raw) ?? null;
}

/**
 * Template gallery (T075, US5): "Start from scratch" first, then the platform templates for both
 * agent types. Filters live in the URL (category, direction, type, q), so a link shares the view
 * and Back steps through it. The chips' counts follow the direction, type and search filters.
 * A click anywhere on a card opens the preview; nothing is created until "Use template" (US5.4).
 */
export function TemplatesPage() {
  const [params, setParams] = useSearchParams();
  const category = pick(params.get("category"), CATEGORIES);
  const direction = pick(params.get("direction"), DIRECTIONS);
  const type = pick(params.get("type"), TYPES);
  const urlQuery = params.get("q") ?? "";
  const [search, setSearch] = useState(urlQuery);
  const q = useDebounced(search.trim(), 250);

  const update = useCallback(
    (patch: Record<string, string | null>, replace = false) => {
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          for (const [k, v] of Object.entries(patch)) {
            if (v) next.set(k, v);
            else next.delete(k);
          }
          return next;
        },
        { replace },
      );
    },
    [setParams],
  );
  // The typed search reaches the URL once it settles, replacing the entry so Back skips keystrokes.
  // A change to q that did not come from here (Back, a shared link, Clear filters) fills the box.
  const written = useRef(urlQuery.trim());
  useEffect(() => {
    if (q !== written.current) {
      written.current = q;
      update({ q: q || null }, true);
    }
  }, [q, update]);
  useEffect(() => {
    if (urlQuery.trim() !== written.current) {
      written.current = urlQuery.trim();
      setSearch(urlQuery);
    }
  }, [urlQuery]);

  const filters = { search: q, direction, agent_type: type };
  const cats = useTemplateCategories(filters);
  const templates = useTemplates({ ...filters, category });
  const [preview, setPreview] = useState<TemplateSummary | null>(null);
  const total = cats.data?.items.reduce((n, c) => n + c.count, 0);
  const items = templates.data?.items ?? [];
  const label = (c: TemplateCategory) => cats.data?.items.find((x) => x.id === c)?.label ?? humanize(c);
  const filtered = Boolean(category || direction || type || q);
  const clearFilters = () => {
    setSearch("");
    setParams({}, { replace: false });
  };
  const head = TITLES[type ?? "all"];
  const chips = cats.data?.items ?? [];

  return (
    <>
      <Link
        to={NEW_AGENT_PATH}
        className="link-underline mb-4 inline-flex w-fit items-center gap-1 rounded-inline text-[13px] text-fg-2 hover:text-fg"
      >
        <ChevronLeft className="size-4" aria-hidden /> Agent type
      </Link>
      <PageHeader title={head.title} description={head.description} />

      <div className="mb-3 flex flex-wrap gap-2" role="group" aria-label="Industry">
        <Chip mono={false} selected={category === null} onClick={() => update({ category: null })}>
          All
          {total != null && <span className="font-mono text-[12px] opacity-70 tnum">{total}</span>}
        </Chip>
        {cats.isPending
          ? Array.from({ length: 5 }, (_, i) => <Skeleton key={i} className="h-9 w-24 rounded-full" />)
          : [
              ...chips,
              // A selected industry that the other filters leave empty stays visible, so it can be cleared.
              ...(category && !chips.some((c) => c.id === category) ? [{ id: category, label: humanize(category), count: 0 }] : []),
            ].map((c) => {
              const Icon = CATEGORY_ICONS[c.id] ?? Phone;
              return (
                <Chip key={c.id} mono={false} selected={category === c.id} onClick={() => update({ category: category === c.id ? null : c.id })}>
                  <Icon aria-hidden />
                  {c.label}
                  <span className="font-mono text-[12px] opacity-70 tnum">{c.count}</span>
                </Chip>
              );
            })}
      </div>

      <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
        <Segmented<TemplateDirection | "all">
          aria-label="Call direction"
          value={direction ?? "all"}
          onValueChange={(v) => update({ direction: v === "all" ? null : v })}
          options={[
            { value: "all", label: "All calls" },
            { value: "inbound", label: "Inbound", icon: <PhoneIncoming aria-hidden /> },
            { value: "outbound", label: "Outbound", icon: <PhoneOutgoing aria-hidden /> },
          ]}
        />
        <Segmented<TemplateAgentType | "all">
          aria-label="Agent type"
          value={type ?? "all"}
          onValueChange={(v) => update({ type: v === "all" ? null : v })}
          options={[
            { value: "all", label: "All types" },
            { value: "single_prompt", label: "Single prompt", icon: <MessageSquareText aria-hidden /> },
            { value: "flow", label: "Flow", icon: <GitBranch aria-hidden /> },
          ]}
        />
        <Input
          className="min-w-0 sm:ml-auto sm:w-[280px]"
          prefix={<Search aria-hidden />}
          placeholder="Search templates"
          aria-label="Search templates"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          suffix={
            search ? (
              <IconButton label="Clear search" className="size-6 [&_svg]:size-3.5" onClick={() => setSearch("")}>
                <X aria-hidden />
              </IconButton>
            ) : undefined
          }
        />
      </div>
      <p className="sr-only" role="status" aria-live="polite">
        {templates.isSuccess ? `${items.length} ${items.length === 1 ? "template" : "templates"}` : ""}
      </p>

      <div
        data-tour="template-grid"
        className={cn(
          "grid grid-cols-[minmax(0,1fr)] gap-4 md:grid-cols-2 xl:grid-cols-3",
          templates.isPlaceholderData && "opacity-70 transition-opacity",
        )}
      >
        <ScratchCard type={type} />

        {templates.isPending ? (
          Array.from({ length: 5 }, (_, i) => <Skeleton key={i} className="h-[208px] w-full rounded-panel" />)
        ) : templates.isError ? (
          <div className="md:col-span-2">
            <EmptyState compact icon={<Phone weight="duotone" />} title="Templates did not load">
              {problemMessage(templates.error, "template")}
            </EmptyState>
          </div>
        ) : items.length === 0 ? (
          <div className="flex md:col-span-1 xl:col-span-2">
            <EmptyState
              compact
              icon={<MagnifyingGlass weight="duotone" />}
              title={q ? `No templates match "${q}"` : "No templates match these filters"}
              actions={
                filtered ? (
                  <Button size="sm" icon={<X aria-hidden />} onClick={clearFilters}>
                    Clear filters
                  </Button>
                ) : undefined
              }
            >
              Try other filters or another word, or start from scratch.
            </EmptyState>
          </div>
        ) : (
          <AnimatePresence initial={false}>
            {items.map((t, i) => {
              const Glyph = TEMPLATE_ICONS[t.icon] ?? Phone;
              return (
                <motion.button
                  key={t.id}
                  type="button"
                  layout
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0, transition: { duration: 0.24, delay: Math.min(i, 8) * 0.03, ease: [0.16, 1, 0.3, 1] } }}
                  exit={{ opacity: 0, scale: 0.97 }}
                  onClick={() => setPreview(t)}
                  aria-haspopup="dialog"
                  className="group flex min-h-[208px] min-w-0 cursor-pointer flex-col gap-4 rounded-panel border border-line bg-surface p-5 text-left shadow-1 transition-[box-shadow,border-color] duration-200 hover:border-accent/45 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
                >
                  <span className="flex w-full items-start justify-between gap-3">
                    <span
                      className={cn("grid size-11 place-items-center rounded-control transition-transform duration-200", CATEGORY_TINT[t.category])}
                    >
                      <Glyph weight="duotone" className="size-6" aria-hidden />
                    </span>
                    <span className="flex flex-wrap justify-end gap-1.5">
                      {t.agent_type === "flow" && (
                        <Badge tone="accent" icon={<GitBranch />}>
                          Flow
                        </Badge>
                      )}
                      <Badge icon={t.direction === "inbound" ? <PhoneIncoming /> : <PhoneOutgoing />}>
                        {t.direction === "inbound" ? "Inbound" : "Outbound"}
                      </Badge>
                    </span>
                  </span>
                  <span className="flex w-full min-w-0 flex-col gap-1">
                    <span className="text-[13px] text-fg-3">{label(t.category)}</span>
                    <span className="text-[15px] font-semibold leading-snug text-fg">{t.name}</span>
                    <span className="line-clamp-3 text-[13px] leading-relaxed text-fg-2">{t.description}</span>
                  </span>
                  <span className="mt-auto text-[13px] font-medium text-accent-text">Preview</span>
                </motion.button>
              );
            })}
          </AnimatePresence>
        )}
      </div>

      <TemplatePreviewDialog template={preview} categoryLabel={preview ? label(preview.category) : ""} onOpenChange={(o) => !o && setPreview(null)} />
    </>
  );
}

const scratchClass =
  "group relative flex min-h-[208px] flex-col gap-4 overflow-hidden rounded-panel border border-dashed border-accent/50 bg-accent-soft/25 p-5 transition-[transform,box-shadow,background-color] duration-200";

/**
 * A blank agent of the selected type: one link when the type filter is set, and a choice of the
 * two types while it shows both.
 */
function ScratchCard({ type }: { type: TemplateAgentType | null }) {
  const body = (
    <>
      <span className="grid size-11 place-items-center rounded-control bg-accent text-white transition-transform duration-200">
        <Plus className="size-5" aria-hidden />
      </span>
      <span className="flex w-full flex-col gap-1">
        <span className="text-[13px] text-fg-3">Any industry</span>
        <span className="text-[15px] font-semibold leading-snug text-fg">Start from scratch</span>
        <span className="text-[13px] leading-relaxed text-fg-2">
          {type === "flow"
            ? "A blank flow with Start, Conversation and End. You design the steps and choose every setting."
            : type === "single_prompt"
              ? "A blank agent with the platform defaults. You write the prompt and choose every setting."
              : "A blank agent with the platform defaults. Choose the type below; it cannot be changed later."}
        </span>
      </span>
    </>
  );
  if (type) {
    return (
      <Link
        to={type === "flow" ? NEW_FLOW_AGENT_PATH : NEW_SINGLE_AGENT_PATH}
        className={cn(scratchClass, "hover:bg-accent-soft/45 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring")}
      >
        {body}
        <span className="mt-auto text-[13px] font-medium text-accent-text">{type === "flow" ? "Open a blank flow" : "Open a blank agent"}</span>
      </Link>
    );
  }
  return (
    <div className={scratchClass}>
      {body}
      <span className="mt-auto flex flex-wrap gap-2">
        <Button asChild size="sm" icon={<MessageSquareText aria-hidden />}>
          <Link to={NEW_SINGLE_AGENT_PATH}>Blank single prompt</Link>
        </Button>
        <Button asChild size="sm" icon={<FlowArrow aria-hidden />}>
          <Link to={NEW_FLOW_AGENT_PATH}>Blank flow</Link>
        </Button>
      </span>
    </div>
  );
}
