import { BookOpenText, MagnifyingGlass } from "@phosphor-icons/react";
import { BookOpen, Bot, FileText, HardDrive, Plus, Search, Upload, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { formatBytes, useKnowledgeBases, type KnowledgeBase } from "../../api/knowledge";
import { problemMessage } from "../../api/problems";
import { Button, EmptyState, FlowChain, IconButton, Input, PageHeader, Pagination, Skeleton, TruncatedText, cn } from "../../components";
import { useDebounced } from "../../lib/useDebounced";
import { relativeDate } from "../agents/AgentCard";
import { CreateKbDialog } from "./CreateKbDialog";
import { KbStatusBadge } from "./kbStatus";

const STEPS = [
  { key: "upload", label: "Upload", icon: <Upload aria-hidden /> },
  { key: "index", label: "Index", icon: <FileText aria-hidden /> },
  { key: "attach", label: "Attach", icon: <Bot aria-hidden /> },
  { key: "answer", label: "Answer", icon: <BookOpen aria-hidden /> },
];

/** Share of documents ready, being processed and failed. */
function ReadyBar({ kb }: { kb: KnowledgeBase }) {
  const total = Math.max(1, kb.document_count);
  const parts = [
    { key: "ready", n: kb.ready_count, className: "bg-success" },
    { key: "processing", n: kb.processing_count, className: "bg-accent animate-pulse" },
    { key: "failed", n: kb.failed_count, className: "bg-danger" },
  ];
  return (
    <div className="mx-5 mt-3 flex h-1.5 gap-0.5 overflow-hidden rounded-full bg-surface-3" aria-hidden>
      {kb.document_count > 0 &&
        parts.map((p) =>
          p.n > 0 ? (
            <motion.span
              key={p.key}
              className={cn("h-full rounded-full", p.className)}
              initial={{ width: 0 }}
              animate={{ width: `${(p.n / total) * 100}%` }}
              transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
            />
          ) : null,
        )}
    </div>
  );
}

function KbCard({ kb }: { kb: KnowledgeBase }) {
  const navigate = useNavigate();
  const to = `/knowledge-base/${kb.id}`;
  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.97 }}
      transition={{ duration: 0.24, ease: [0.16, 1, 0.3, 1] }}
      className="flex min-w-0"
    >
      <article
        onClick={(e) => {
          if (!(e.target as HTMLElement).closest("a,button")) navigate(to);
        }}
        className="group relative flex min-w-0 flex-1 cursor-pointer flex-col rounded-panel border border-line bg-surface shadow-1 transition-[transform,box-shadow,border-color] duration-200 hover:border-accent/45 focus-within:border-accent/45"
      >
        <div className="flex items-start gap-3 px-5 pb-3 pt-4">
          <span className="grid size-10 shrink-0 place-items-center rounded-control bg-accent-soft text-accent-text transition-[background-color,color] duration-200 group-hover:bg-accent group-hover:text-white">
            <BookOpen className="size-5" aria-hidden />
          </span>
          <div className="flex min-w-0 flex-1 flex-col gap-0.5 pt-px">
            <h3 className="min-w-0 text-[15px] font-semibold leading-snug text-fg">
              <Link to={to} className="block rounded-inline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring">
                <TruncatedText focusable={false}>{kb.name}</TruncatedText>
              </Link>
            </h3>
            <p className={cn("line-clamp-2 min-h-[2lh] text-[13px] leading-snug", kb.description ? "text-fg-2" : "italic text-fg-3")}>
              {kb.description || "No description"}
            </p>
          </div>
        </div>
        <dl className="mx-5 grid grid-cols-3 gap-2 border-y border-line py-3">
          {[
            { icon: <FileText />, label: "Documents", value: kb.document_count.toLocaleString() },
            { icon: <HardDrive />, label: "Size", value: formatBytes(kb.total_bytes) },
            { icon: <Bot />, label: "Agents", value: kb.agent_count.toLocaleString() },
          ].map((r) => (
            <div key={r.label} className="flex min-w-0 flex-col gap-0.5">
              <dt className="flex items-center gap-1.5 text-[12px] text-fg-3 [&_svg]:size-3.5">
                {r.icon}
                {r.label}
              </dt>
              <dd className="font-mono text-[14px] text-fg tnum">{r.value}</dd>
            </div>
          ))}
        </dl>
        <ReadyBar kb={kb} />
        <div className="flex items-center justify-between gap-2 px-5 pb-3 pt-2.5">
          <KbStatusBadge status={kb.status} />
          <span className="text-[12px] text-fg-3">Updated {relativeDate(kb.updated_at)}</span>
        </div>
      </article>
    </motion.div>
  );
}

/** Knowledge bases (T066, T098): a card per base with its status, and a create flow that goes straight to uploading. */
export function KnowledgeListPage() {
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const q = useDebounced(search.trim(), 250);
  const kbs = useKnowledgeBases(q, page);
  const [creating, setCreating] = useState(false);
  const items = kbs.data?.items ?? [];
  const total = kbs.data?.total ?? 0;
  const firstLoad = kbs.isPending;
  const empty = !firstLoad && total === 0 && !q;
  const openNew = () => setCreating(true);

  return (
    <>
      <PageHeader
        title="Knowledge"
        description="Documents your agents can search during a call, for answers grounded in your own policies and prices."
        actions={
          empty ? undefined : (
            <Button variant="primary" icon={<Plus aria-hidden />} onClick={openNew}>
              New knowledge base
            </Button>
          )
        }
      />

      {empty ? (
        <section className="relative overflow-hidden rounded-feature border border-line bg-surface shadow-2">
          <div className="relative grid gap-8 px-6 py-10 sm:px-10 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] lg:items-center">
            <EmptyState
              className="px-0 py-0"
              icon={<BookOpenText weight="duotone" />}
              title="Give your agents something to read"
              actions={
                <Button variant="primary" icon={<Plus aria-hidden />} onClick={openNew}>
                  New knowledge base
                </Button>
              }
            >
              Upload PDF and Word (.docx) documents up to 20 MB each. They are indexed in the background; attach the knowledge base to an agent and it
              looks things up while it talks.
            </EmptyState>
            <div className="rounded-panel border border-line bg-surface-2/70 px-5 py-6">
              <p className="text-[13px] font-medium text-fg">From document to answer</p>
              <FlowChain label="From document to answer" nodes={STEPS} active="upload" flow stack="tight" className="mt-5" />
              <p className="mt-5 text-[13px] leading-relaxed text-fg-2">
                Searches take a fraction of a second, so the caller hears an answer from your documents without a long pause.
              </p>
            </div>
          </div>
        </section>
      ) : (
        <>
          <div className="mb-5 flex flex-col gap-3 md:flex-row md:items-center">
            <Input
              className="min-w-0 md:w-[340px]"
              prefix={<Search aria-hidden />}
              placeholder="Search knowledge bases"
              aria-label="Search knowledge bases"
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
            <p className="text-[13px] text-fg-3 md:ml-auto" aria-live="polite">
              {firstLoad ? "" : `${total.toLocaleString()} ${total === 1 ? "knowledge base" : "knowledge bases"}${q ? " found" : ""}`}
            </p>
          </div>
          {firstLoad ? (
            <div className="grid grid-cols-[minmax(0,1fr)] gap-4 md:grid-cols-2 xl:grid-cols-3" aria-busy="true" aria-label="Loading knowledge bases">
              {Array.from({ length: 6 }, (_, i) => (
                <Skeleton key={i} className="h-[206px] w-full rounded-panel" />
              ))}
            </div>
          ) : kbs.isError ? (
            <EmptyState icon={<BookOpenText weight="duotone" />} title="Knowledge bases did not load">
              {problemMessage(kbs.error, "knowledge base")}
            </EmptyState>
          ) : items.length === 0 ? (
            <EmptyState
              icon={<MagnifyingGlass weight="duotone" />}
              title={`No knowledge bases match "${q}"`}
              actions={<Button onClick={() => setSearch("")}>Clear search</Button>}
            >
              Search matches part of a name.
            </EmptyState>
          ) : (
            <div className={kbs.isPlaceholderData ? "opacity-60 transition-opacity" : "transition-opacity"}>
              <div className="grid grid-cols-[minmax(0,1fr)] gap-4 md:grid-cols-2 xl:grid-cols-3">
                <AnimatePresence>
                  {items.map((kb) => (
                    <KbCard key={kb.id} kb={kb} />
                  ))}
                </AnimatePresence>
              </div>
              {kbs.data && kbs.data.total_pages > 1 && (
                <Pagination
                  className="mt-4 px-0"
                  page={page}
                  totalPages={kbs.data.total_pages}
                  total={total}
                  pageSize={24}
                  noun="knowledge bases"
                  onPageChange={setPage}
                />
              )}
            </div>
          )}
        </>
      )}
      <CreateKbDialog open={creating} onOpenChange={setCreating} onCreated={(kb) => navigate(`/knowledge-base/${kb.id}?upload=1`)} />
    </>
  );
}
