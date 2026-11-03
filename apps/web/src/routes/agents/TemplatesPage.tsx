import { MagnifyingGlass, Phone } from "@phosphor-icons/react";
import { ChevronLeft, PhoneIncoming, PhoneOutgoing, Plus, Search, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";
import { Link } from "react-router";
import { useTemplateCategories, useTemplates, type TemplateCategory, type TemplateSummary } from "../../api/agents";
import { problemMessage } from "../../api/problems";
import { Badge, Chip, EmptyState, IconButton, Input, PageHeader, Skeleton, cn } from "../../components";
import { useDebounced } from "../../lib/useDebounced";
import { CATEGORY_ICONS, CATEGORY_TINT, TEMPLATE_ICONS } from "./templateIcons";
import { TemplatePreviewDialog } from "./TemplatePreviewDialog";

/**
 * Template picker (T075, US5): "Start from scratch" first, then the platform templates with an
 * "All" chip plus one per industry, and search by name. A click anywhere on a card opens the
 * preview; nothing is created until "Use template" (US5.4).
 */
export function TemplatesPage() {
  const [category, setCategory] = useState<TemplateCategory | null>(null);
  const [search, setSearch] = useState("");
  const q = useDebounced(search.trim(), 250);
  const cats = useTemplateCategories();
  const templates = useTemplates(category, q);
  const [preview, setPreview] = useState<TemplateSummary | null>(null);
  const total = cats.data?.items.reduce((n, c) => n + c.count, 0);
  const items = templates.data?.items ?? [];
  const label = (c: TemplateCategory) => cats.data?.items.find((x) => x.id === c)?.label ?? c;

  return (
    <>
      <Link to="/agents/new" className="link-underline mb-4 inline-flex w-fit items-center gap-1 rounded-inline text-[13px] text-fg-2 hover:text-fg">
        <ChevronLeft className="size-4" aria-hidden /> Agent type
      </Link>
      <PageHeader
        title="Start a single-prompt agent"
        description="Begin from a blank agent, or from a template written for your industry and adjust it."
      />

      <div className="mb-5 flex flex-col gap-3 lg:flex-row lg:items-center">
        <div role="group" aria-label="Industry" className="flex flex-wrap gap-2">
          <Chip mono={false} selected={category === null} onClick={() => setCategory(null)}>
            All
            {total != null && <span className="font-mono text-[11.5px] opacity-70 tnum">{total}</span>}
          </Chip>
          {cats.isPending
            ? Array.from({ length: 5 }, (_, i) => <Skeleton key={i} className="h-9 w-24 rounded-full" />)
            : cats.data?.items.map((c) => {
                const Icon = CATEGORY_ICONS[c.id];
                return (
                  <Chip key={c.id} mono={false} selected={category === c.id} onClick={() => setCategory(category === c.id ? null : c.id)}>
                    <Icon aria-hidden />
                    {c.label}
                    <span className="font-mono text-[11.5px] opacity-70 tnum">{c.count}</span>
                  </Chip>
                );
              })}
        </div>
        <Input
          className="min-w-0 lg:ml-auto lg:w-[300px]"
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

      <div
        data-tour="template-grid"
        className={cn(
          "grid grid-cols-[minmax(0,1fr)] gap-4 md:grid-cols-2 xl:grid-cols-3",
          templates.isPlaceholderData && "opacity-70 transition-opacity",
        )}
      >
        <Link
          to="/agents/new/single"
          className="group relative flex min-h-[208px] flex-col gap-4 overflow-hidden rounded-panel border border-dashed border-accent/50 bg-accent-soft/25 p-5 transition-[transform,box-shadow,background-color] duration-200 hover:-translate-y-0.5 hover:bg-accent-soft/45 hover:shadow-glow focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
        >
          <span className="grid size-11 place-items-center rounded-control grad-action text-white shadow-[0_8px_18px_-10px_rgb(51_70_232/0.8)] transition-transform duration-200 group-hover:scale-105">
            <Plus className="size-5" aria-hidden />
          </span>
          <span className="flex w-full flex-col gap-1">
            <span className="text-[12.5px] text-fg-3">Any industry</span>
            <span className="text-[15px] font-semibold leading-snug text-fg">Start from scratch</span>
            <span className="text-[13px] leading-relaxed text-fg-2">
              A blank agent with the platform defaults. You write the prompt and choose every setting.
            </span>
          </span>
          <span className="mt-auto text-[13px] font-medium text-accent-text">Open a blank agent</span>
        </Link>

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
            <EmptyState compact icon={<MagnifyingGlass weight="duotone" />} title={q ? `No templates match "${q}"` : "No templates in this industry"}>
              Try another word, or start from scratch.
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
                  className="group flex min-h-[208px] min-w-0 cursor-pointer flex-col gap-4 rounded-panel border border-line bg-surface p-5 text-left shadow-1 transition-[box-shadow,border-color] duration-200 hover:border-accent/45 hover:shadow-glow focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
                >
                  <span className="flex w-full items-start justify-between gap-3">
                    <span
                      className={cn(
                        "grid size-11 place-items-center rounded-control transition-transform duration-200 group-hover:scale-105",
                        CATEGORY_TINT[t.category],
                      )}
                    >
                      <Glyph weight="duotone" className="size-6" aria-hidden />
                    </span>
                    <Badge icon={t.direction === "inbound" ? <PhoneIncoming /> : <PhoneOutgoing />}>
                      {t.direction === "inbound" ? "Inbound" : "Outbound"}
                    </Badge>
                  </span>
                  <span className="flex w-full min-w-0 flex-col gap-1">
                    <span className="text-[12.5px] text-fg-3">{label(t.category)}</span>
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
