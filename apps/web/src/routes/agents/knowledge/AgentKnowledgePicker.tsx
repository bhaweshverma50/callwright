import { BookOpenText, MagnifyingGlass } from "@phosphor-icons/react";
import { BookOpen, Check, ExternalLink, FileText, Lightbulb, Link2, Plus, Search, Unlink, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useMemo, useState } from "react";
import { Link } from "react-router";
import { MAX_KBS_PER_AGENT, useAllKnowledgeBases, type KnowledgeBase } from "../../../api/knowledge";
import { problemMessage } from "../../../api/problems";
import { Badge, Button, Dialog, EmptyState, IconButton, Input, Panel, Skeleton, cn, toast } from "../../../components";
import { TabHeader } from "../tools/TabHeader";
import type { EditorPanelProps } from "../editor/panels";
import { CreateKbDialog } from "../../knowledge/CreateKbDialog";
import { KbStatusBadge } from "../../knowledge/kbStatus";
import { UploadDialog } from "../../knowledge/UploadDialog";

function sameSet(a: string[], b: string[]) {
  return a.length === b.length && a.every((x) => b.includes(x));
}

function KbOption({
  kb,
  on,
  disabled,
  reason,
  onToggle,
}: {
  kb: KnowledgeBase;
  on: boolean;
  disabled: boolean;
  reason?: string;
  onToggle: () => void;
}) {
  return (
    <li>
      <button
        type="button"
        role="checkbox"
        aria-checked={on}
        aria-disabled={disabled || undefined}
        disabled={disabled}
        onClick={onToggle}
        className={cn(
          "flex w-full min-w-0 items-center gap-3 rounded-panel border px-3.5 py-3 text-left transition-[background-color,border-color,box-shadow] duration-150",
          on
            ? "border-accent bg-accent-soft/45 shadow-[0_0_0_1px_var(--accent)]"
            : "border-line bg-surface hover:border-accent/45 hover:bg-surface-2/60",
          disabled && "cursor-not-allowed opacity-60 hover:border-line hover:bg-surface",
          "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
        )}
      >
        <span
          className={cn(
            "grid size-8 shrink-0 place-items-center rounded-control [&_svg]:size-4",
            on ? "bg-accent text-white" : "bg-accent-soft text-accent-text",
          )}
        >
          <BookOpen aria-hidden />
        </span>
        <span className="flex min-w-0 flex-1 flex-col gap-0.5">
          <span className="truncate text-[14px] font-medium text-fg">{kb.name}</span>
          <span className="truncate text-[12px] text-fg-3">
            {reason ?? `${kb.ready_count} of ${kb.document_count} ${kb.document_count === 1 ? "document" : "documents"} ready`}
          </span>
        </span>
        {disabled ? (
          <KbStatusBadge status={kb.status} />
        ) : (
          <span
            aria-hidden
            className={cn(
              "grid size-5 shrink-0 place-items-center rounded-full border transition-[background-color,border-color,transform] duration-200",
              on ? "scale-100 border-transparent bg-accent text-white" : "scale-90 border-line-strong bg-surface text-transparent",
            )}
          >
            <Check strokeWidth={3} className="size-3" />
          </span>
        )}
      </button>
    </li>
  );
}

/**
 * Attach knowledge bases to an agent (T080, T099). Ready bases can be picked (up to 10); bases
 * without a processed document are listed apart and cannot be. Confirm stays disabled while the
 * selection equals what is attached. A shortcut creates a base and opens its upload in place.
 */
export function AgentKnowledgePicker({
  open,
  onOpenChange,
  attachedIds,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  attachedIds: string[];
  onConfirm: (ids: string[]) => void;
}) {
  const kbs = useAllKnowledgeBases(open);
  const [search, setSearch] = useState("");
  const [selection, setSelection] = useState<string[] | null>(null);
  const [creating, setCreating] = useState(false);
  const [uploadTo, setUploadTo] = useState<KnowledgeBase | null>(null);
  const selected = selection ?? attachedIds;
  const q = search.trim().toLowerCase();
  const all = kbs.data ?? [];
  const matching = all.filter((k) => !q || k.name.toLowerCase().includes(q) || k.description.toLowerCase().includes(q));
  const ready = matching.filter((k) => k.attachable || selected.includes(k.id));
  const notReady = matching.filter((k) => !k.attachable && !selected.includes(k.id));
  const full = selected.length >= MAX_KBS_PER_AGENT;
  const unchanged = sameSet(selected, attachedIds);

  const toggle = (id: string) => setSelection(selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id]);
  const close = (o: boolean) => {
    if (!o) {
      setSelection(null);
      setSearch("");
    }
    onOpenChange(o);
  };

  return (
    <>
      <Dialog
        open={open && !creating && uploadTo === null}
        onOpenChange={close}
        size="lg"
        icon={<Link2 />}
        title="Attach knowledge"
        description={`The agent searches these during calls. ${selected.length} of ${MAX_KBS_PER_AGENT} selected.`}
        footer={
          <>
            <Button variant="ghost" icon={<Plus aria-hidden />} className="mr-auto" onClick={() => setCreating(true)}>
              New and upload
            </Button>
            <Button onClick={() => close(false)}>Cancel</Button>
            <Button
              variant="primary"
              icon={<Check aria-hidden />}
              disabled={unchanged}
              onClick={() => {
                onConfirm(selected);
                close(false);
              }}
            >
              Confirm
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-3">
          <Input
            prefix={<Search aria-hidden />}
            placeholder="Search knowledge bases"
            aria-label="Search knowledge bases"
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
          <div className="max-h-[min(52vh,440px)] overflow-y-auto pr-1">
            {kbs.isPending ? (
              <div className="flex flex-col gap-2" aria-busy="true" aria-label="Loading knowledge bases">
                {Array.from({ length: 3 }, (_, i) => (
                  <Skeleton key={i} className="h-[62px] w-full rounded-panel" />
                ))}
              </div>
            ) : kbs.isError ? (
              <EmptyState compact icon={<BookOpenText weight="duotone" />} title="Knowledge bases did not load">
                {problemMessage(kbs.error, "knowledge base")}
              </EmptyState>
            ) : all.length === 0 ? (
              <EmptyState
                compact
                icon={<BookOpenText weight="duotone" />}
                title="No knowledge bases yet"
                actions={
                  <Button variant="primary" icon={<Plus aria-hidden />} onClick={() => setCreating(true)}>
                    New knowledge base
                  </Button>
                }
              >
                Create one and upload PDF or Word (.docx) documents; the agent can search them once they are processed.
              </EmptyState>
            ) : matching.length === 0 ? (
              <EmptyState compact icon={<MagnifyingGlass weight="duotone" />} title={`Nothing matches "${search.trim()}"`} />
            ) : (
              <div className="flex flex-col gap-4">
                {ready.length > 0 && (
                  <section className="flex flex-col gap-2" aria-label="Ready">
                    <h3 className="text-[12px] font-medium text-fg-3">Ready</h3>
                    <ul className="flex flex-col gap-2">
                      {ready.map((k) => (
                        <KbOption
                          key={k.id}
                          kb={k}
                          on={selected.includes(k.id)}
                          disabled={full && !selected.includes(k.id)}
                          onToggle={() => toggle(k.id)}
                        />
                      ))}
                    </ul>
                  </section>
                )}
                {notReady.length > 0 && (
                  <section className="flex flex-col gap-2" aria-label="Not ready">
                    <h3 className="text-[12px] font-medium text-fg-3">Not ready</h3>
                    <ul className="flex flex-col gap-2">
                      {notReady.map((k) => (
                        <KbOption
                          key={k.id}
                          kb={k}
                          on={false}
                          disabled
                          reason={k.document_count === 0 ? "No documents yet" : "Documents are still being processed"}
                          onToggle={() => undefined}
                        />
                      ))}
                    </ul>
                  </section>
                )}
              </div>
            )}
          </div>
        </div>
      </Dialog>
      <CreateKbDialog
        open={creating}
        onOpenChange={setCreating}
        onCreated={(kb) => {
          setCreating(false);
          setUploadTo(kb);
        }}
      />
      {uploadTo && (
        <UploadDialog
          open
          onOpenChange={(o) => !o && setUploadTo(null)}
          kbId={uploadTo.id}
          kbName={uploadTo.name}
          onUploaded={() => toast({ title: "Processing", description: `${uploadTo.name} can be attached as soon as its document is ready.` })}
        />
      )}
    </>
  );
}

/** The agent's Knowledge tab: attached bases with their status, plus the picker. */
export function KnowledgeTab({ config, update }: EditorPanelProps) {
  const ids = (config.kb_ids ?? []) as string[];
  const kbs = useAllKnowledgeBases(true);
  const [picking, setPicking] = useState(false);
  const byId = useMemo(() => new Map((kbs.data ?? []).map((k) => [k.id, k])), [kbs.data]);
  const attached = ids.map((id) => byId.get(id)).filter((k): k is KnowledgeBase => Boolean(k));

  return (
    <div className="flex flex-col gap-4">
      <Panel bodyClassName="p-0">
        <TabHeader
          title="Knowledge"
          icon={<BookOpen aria-hidden />}
          description={`Documents the agent can search while it talks. ${ids.length} of ${MAX_KBS_PER_AGENT} attached.`}
          actions={
            ids.length > 0 ? (
              <Button size="sm" icon={<Link2 aria-hidden />} onClick={() => setPicking(true)}>
                Change
              </Button>
            ) : undefined
          }
        />
        {kbs.isPending && ids.length > 0 ? (
          <div className="flex flex-col gap-3 p-5">
            {ids.map((id) => (
              <Skeleton key={id} className="h-[64px] w-full rounded-panel" />
            ))}
          </div>
        ) : attached.length === 0 ? (
          <div className="relative overflow-hidden">
            <EmptyState
              compact
              className="relative"
              icon={<BookOpenText weight="duotone" />}
              title="No knowledge attached"
              actions={
                <Button variant="primary" icon={<Link2 aria-hidden />} onClick={() => setPicking(true)}>
                  Attach knowledge
                </Button>
              }
            >
              Attach a knowledge base and the agent looks up answers in your PDF and Word documents during calls.
            </EmptyState>
          </div>
        ) : (
          <ul className="divide-y divide-line" aria-label="Attached knowledge bases">
            <AnimatePresence initial={false}>
              {attached.map((kb) => (
                <motion.li
                  key={kb.id}
                  layout
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, x: -12 }}
                  className="group flex min-w-0 items-center gap-3.5 px-5 py-4 transition-colors duration-150 hover:bg-surface-2/50"
                >
                  <span className="grid size-10 shrink-0 place-items-center rounded-control bg-accent-soft text-accent-text [&_svg]:size-5">
                    <BookOpen aria-hidden />
                  </span>
                  <div className="flex min-w-0 flex-1 flex-col gap-1">
                    <Link to={`/knowledge-base/${kb.id}`} className="link-underline w-fit max-w-full truncate text-[14px] font-semibold text-fg">
                      {kb.name}
                    </Link>
                    <span className="flex flex-wrap items-center gap-1.5 text-[12px] text-fg-3">
                      <KbStatusBadge status={kb.status} />
                      <span className="inline-flex items-center gap-1">
                        <FileText className="size-3.5" aria-hidden />
                        {kb.ready_count} of {kb.document_count} ready
                      </span>
                    </span>
                  </div>
                  <div className="-mr-2 flex shrink-0 items-center opacity-100 transition-opacity sm:opacity-60 sm:group-focus-within:opacity-100 sm:group-hover:opacity-100">
                    <IconButton label={`Open ${kb.name}`} className="size-8" asChild>
                      <Link to={`/knowledge-base/${kb.id}`}>
                        <ExternalLink className="size-4" aria-hidden />
                      </Link>
                    </IconButton>
                    <IconButton
                      label={`Detach ${kb.name}`}
                      className="size-8 hover:bg-danger-soft hover:text-danger-text"
                      onClick={() =>
                        update((d) => {
                          d.kb_ids = ((d.kb_ids ?? []) as string[]).filter((x) => x !== kb.id);
                        })
                      }
                    >
                      <Unlink className="size-4" aria-hidden />
                    </IconButton>
                  </div>
                </motion.li>
              ))}
            </AnimatePresence>
          </ul>
        )}
      </Panel>
      {ids.length > 0 && (
        <div className="flex items-start gap-2.5 rounded-panel border border-line bg-surface px-4 py-3 text-[13px] text-fg-2">
          <Lightbulb className="mt-0.5 size-4 shrink-0 text-accent-text" aria-hidden />
          <p>
            The agent gets a <span className="font-mono text-fg">kb_search</span> tool and says a short line while it looks things up. New documents
            count at once; no need to publish again.
          </p>
        </div>
      )}
      {ids.length > attached.length && !kbs.isPending && (
        <Badge tone="warning">
          {ids.length - attached.length} attached knowledge {ids.length - attached.length === 1 ? "base was" : "bases were"} deleted
        </Badge>
      )}
      <AgentKnowledgePicker
        open={picking}
        onOpenChange={setPicking}
        attachedIds={ids}
        onConfirm={(next) =>
          update((d) => {
            d.kb_ids = next;
          })
        }
      />
    </div>
  );
}
