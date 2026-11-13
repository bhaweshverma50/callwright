import { BookOpenText, FileArrowUp } from "@phosphor-icons/react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Archive,
  Bot,
  ChevronLeft,
  Cloud,
  ExternalLink,
  CircleCheck,
  CloudUpload,
  Eye,
  FileText,
  FileType2,
  HardDrive,
  MoreHorizontal,
  Pencil,
  RotateCw,
  Trash2,
  TriangleAlert,
} from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import {
  archiveDocument,
  deleteDocument,
  deleteKnowledgeBase,
  documentUrl,
  type KbDocument,
  kbKeys,
  type KbUser,
  kbUsersOf,
  type KnowledgeBase,
  MAX_FILE_MB,
  daysLeft,
  reprocessDocument,
  restoreDocument,
  useArchivedDocuments,
  useDocuments,
  useKnowledgeBase,
  useSources,
} from "../../api/knowledge";
import { isApiError } from "../../api/errors";
import { problemMessage } from "../../api/problems";
import {
  Badge,
  Button,
  CopyButton,
  Dialog,
  EmptyState,
  IconButton,
  Menu,
  MenuContent,
  MenuItem,
  MenuTrigger,
  Panel,
  Skeleton,
  Table,
  Tabs,
  Tooltip,
  TruncatedText,
  WorkLayout,
  toast,
  type Column,
} from "../../components";
import { RecordNotFound } from "../NotFound";
import { CreateKbDialog } from "./CreateKbDialog";
import { DocStatusBadge, ERROR_HELP, KbStatusBadge } from "./kbStatus";
import { SearchPreviewPanel } from "./SearchPreviewPanel";
import { UploadDialog } from "./UploadDialog";
import { AddDriveSourceDialog } from "./sources/AddDriveSourceDialog";
import { SourceCard } from "./sources/SourceCard";
import { agentPath, KNOWLEDGE_PATH } from "../../lib/paths";
import { formatBytes, timeAgo } from "../../lib/format";

const ID = /^kb_[0-9A-HJKMNP-TV-Z]{26}$/;

function Stat({ icon, label, value }: { icon: ReactNode; label: string; value: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-1 rounded-panel border border-line bg-surface px-4 py-3 shadow-1">
      <span className="flex items-center gap-1.5 text-[12px] text-fg-3 [&_svg]:size-3.5">
        {icon}
        {label}
      </span>
      <span className="font-mono text-[18px] font-medium text-fg tnum">{value}</span>
    </div>
  );
}

/** One knowledge base (T068): documents with live status, retry, preview, delete, and a search preview. */
export function KnowledgeBasePage() {
  const { id } = useParams();
  const valid = Boolean(id && ID.test(id));
  const kb = useKnowledgeBase(valid ? id : undefined);
  if (!valid || (kb.error && isApiError(kb.error) && kb.error.status === 404)) {
    return <RecordNotFound kind="knowledge base" backTo={KNOWLEDGE_PATH} backLabel="Back to Knowledge" />;
  }
  if (kb.error) {
    return (
      <EmptyState icon={<BookOpenText weight="duotone" />} title="The knowledge base did not load">
        {problemMessage(kb.error, "knowledge base")}
      </EmptyState>
    );
  }
  if (!kb.data) return <PageSkeleton />;
  return <KbView kb={kb.data} />;
}

function KbView({ kb }: { kb: KnowledgeBase }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [uploadOpen, setUploadOpen] = useState(params.get("upload") === "1");
  const [renaming, setRenaming] = useState(false);
  const [deletingKb, setDeletingKb] = useState(false);
  const [inUse, setInUse] = useState<KbUser[] | null>(null);
  const [deletingDoc, setDeletingDoc] = useState<KbDocument | null>(null);
  const docs = useDocuments(kb.id);
  const sources = useSources(kb.id);
  const [addingSource, setAddingSource] = useState(false);
  const [tab, setTab] = useState<"documents" | "archived">("documents");
  const archived = useArchivedDocuments(kb.id, tab === "archived");

  const refresh = () => void qc.invalidateQueries({ queryKey: kbKeys.all });
  // When a source finishes syncing, its documents, the archived list and the counts changed:
  // refetch them (only the sources list polls while a sync runs).
  const wasBusy = useRef(new Set<string>());
  useEffect(() => {
    const busyNow = new Set((sources.data?.items ?? []).filter((s) => s.state === "pending" || s.state === "syncing").map((s) => s.id));
    const finished = [...wasBusy.current].some((id) => !busyNow.has(id));
    wasBusy.current = busyNow;
    if (finished) void qc.invalidateQueries({ queryKey: kbKeys.all });
  }, [sources.data, qc]);
  const removeDoc = useMutation({
    mutationFn: (d: KbDocument) => deleteDocument(kb.id, d.id),
    onSuccess: (_r, d) => {
      setDeletingDoc(null);
      refresh();
      toast({ tone: "success", title: "Document deleted", description: `${d.display_name ?? d.file_name} no longer appears in searches.` });
    },
    onError: (e) => toast({ tone: "error", title: "Not deleted", description: problemMessage(e, "document") }),
  });
  const restore = useMutation({
    mutationFn: (d: KbDocument) => restoreDocument(kb.id, d.id),
    onSuccess: (_r, d) => {
      refresh();
      toast({ tone: "success", title: "Document restored", description: `${d.display_name ?? d.file_name} is back in search.` });
    },
    onError: (e) => toast({ tone: "error", title: "Not restored", description: problemMessage(e, "document") }),
  });
  const archiveKept = useMutation({
    mutationFn: (d: KbDocument) => archiveDocument(kb.id, d.id),
    onSuccess: (_r, d) => {
      refresh();
      toast({ tone: "success", title: "Document archived", description: `${d.display_name ?? d.file_name} left search for 30 days.` });
    },
    onError: (e) => toast({ tone: "error", title: "Not archived", description: problemMessage(e, "document") }),
  });
  const retry = useMutation({
    mutationFn: (d: KbDocument) => reprocessDocument(kb.id, d.id),
    onSuccess: () => refresh(),
    onError: (e) => toast({ tone: "error", title: "Not retried", description: problemMessage(e, "document") }),
  });
  const removeKb = useMutation({
    mutationFn: (confirm: boolean) => deleteKnowledgeBase(kb.id, confirm),
    onSuccess: () => {
      setDeletingKb(false);
      setInUse(null);
      refresh();
      toast({ tone: "success", title: "Knowledge base deleted", description: `${kb.name} and its documents are gone.` });
      navigate(KNOWLEDGE_PATH);
    },
    onError: (e) => {
      setDeletingKb(false);
      const users = kbUsersOf(e);
      if (users) setInUse(users);
      else toast({ tone: "error", title: "Not deleted", description: problemMessage(e, "knowledge base") });
    },
  });

  const preview = async (d: KbDocument) => {
    const tab = window.open("about:blank", "_blank");
    if (tab) tab.opener = null; // the served document must not reach back into this app
    try {
      const url = await documentUrl(kb.id, d.id);
      if (tab) tab.location.href = url;
    } catch (e) {
      tab?.close();
      toast({ tone: "error", title: "Preview unavailable", description: problemMessage(e, "document") });
    }
  };

  const emptyState = (
    <EmptyState
      compact
      icon={<FileArrowUp weight="duotone" />}
      title="No documents yet"
      actions={
        <Button variant="primary" icon={<CloudUpload aria-hidden />} onClick={() => setUploadOpen(true)}>
          Upload a document
        </Button>
      }
    >
      Upload a PDF or Word (.docx) file up to {MAX_FILE_MB} MB. It becomes searchable once it is processed.
    </EmptyState>
  );

  const columns: Column<KbDocument>[] = [
    {
      key: "name",
      header: "Document",
      cell: (d) => (
        <div className="flex min-w-0 items-center gap-3 py-2">
          <span className="grid size-8 shrink-0 place-items-center rounded-control bg-surface-2 text-fg-2 [&_svg]:size-4">
            {d.file_type === "pdf" ? <FileText aria-hidden /> : <FileType2 aria-hidden />}
          </span>
          <div className="flex min-w-0 flex-col gap-0.5">
            <span className="max-w-[340px] truncate font-medium text-fg">{d.display_name ?? d.file_name}</span>
            <span className="flex min-w-0 items-center gap-2 text-[12px] text-fg-3">
              {(d.display_name ?? d.file_name) !== d.file_name && <span className="truncate font-mono">{d.file_name}</span>}
              <span className="whitespace-nowrap uppercase">{d.file_type}</span>
              <span className="md:hidden">
                <DocStatusBadge status={d.status} />
              </span>
            </span>
            {d.source && (
              <span className="flex min-w-0 items-center gap-1.5 text-[12px] text-fg-3">
                <Badge icon={<Cloud />}>Google Drive</Badge>
                {d.source.file_missing && <Badge tone="warning">File missing in Drive</Badge>}
                <span className="truncate">{d.source.path ? `${d.source.root_name}/${d.source.path}` : d.source.root_name}</span>
                {d.source.web_view_link && (
                  <a
                    href={d.source.web_view_link}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="link-underline inline-flex items-center gap-0.5 whitespace-nowrap text-accent-text"
                  >
                    Open in Drive <ExternalLink className="size-3" aria-hidden />
                  </a>
                )}
              </span>
            )}
            {d.status === "failed" && (
              <span className="flex max-w-[420px] items-start gap-1.5 whitespace-normal text-[12px] leading-snug text-danger-text">
                <TriangleAlert className="mt-px size-3.5 shrink-0" aria-hidden />
                {ERROR_HELP[d.error_code ?? "internal"] ?? d.error_message}
              </span>
            )}
          </div>
        </div>
      ),
    },
    { key: "status", header: "Status", hideOnNarrow: true, cell: (d) => <DocStatusBadge status={d.status} /> },
    {
      key: "pages",
      header: "Pages",
      numeric: true,
      hideOnNarrow: true,
      cell: (d) => d.page_count ?? (d.file_type === "docx" && d.status === "ready" ? "n/a" : ""),
    },
    {
      key: "size",
      header: "Size",
      numeric: true,
      hideOnNarrow: true,
      cell: (d) => <span className="whitespace-nowrap">{formatBytes(d.file_size)}</span>,
    },
    {
      key: "added",
      header: tab === "archived" ? "Deleted in" : "Added",
      hideOnNarrow: true,
      cell: (d) =>
        d.status === "archived" ? (
          <span className="whitespace-nowrap text-fg-2">{daysLeft(d.archived_at)} days</span>
        ) : (
          <span className="whitespace-nowrap text-fg-2">{timeAgo(d.created_at)}</span>
        ),
    },
    {
      key: "actions",
      header: <span className="sr-only">Actions</span>,
      align: "right",
      cell: (d) => (
        <div className="-mr-2 flex items-center justify-end">
          {d.status === "failed" && (
            <Button
              size="sm"
              variant="ghost"
              icon={<RotateCw aria-hidden />}
              pending={retry.isPending && retry.variables?.id === d.id}
              onClick={() => retry.mutate(d)}
            >
              Retry
            </Button>
          )}
          <IconButton label={`Open ${d.display_name ?? d.file_name}`} className="size-8" onClick={() => void preview(d)}>
            <Eye className="size-4" aria-hidden />
          </IconButton>
          {d.status === "archived" ? (
            <Button
              size="sm"
              variant="ghost"
              icon={<RotateCw aria-hidden />}
              pending={restore.isPending && restore.variables?.id === d.id}
              onClick={() => restore.mutate(d)}
            >
              Restore
            </Button>
          ) : d.source?.file_missing ? (
            <Button
              size="sm"
              variant="ghost"
              icon={<Archive aria-hidden />}
              pending={archiveKept.isPending && archiveKept.variables?.id === d.id}
              onClick={() => archiveKept.mutate(d)}
            >
              Archive
            </Button>
          ) : (
            !d.managed && (
              <IconButton
                label={`Delete ${d.display_name ?? d.file_name}`}
                className="size-8 hover:bg-danger-soft hover:text-danger-text"
                onClick={() => setDeletingDoc(d)}
              >
                <Trash2 className="size-4" aria-hidden />
              </IconButton>
            )
          )}
        </div>
      ),
    },
  ];

  return (
    <div className="flex flex-col">
      <Link
        to={KNOWLEDGE_PATH}
        className="link-underline mb-4 inline-flex w-fit items-center gap-1 rounded-inline text-[13px] text-fg-2 hover:text-fg"
      >
        <ChevronLeft className="size-4" aria-hidden /> Knowledge
      </Link>
      <header className="mb-6 flex flex-wrap items-end justify-between gap-x-6 gap-y-4">
        <div className="flex min-w-0 flex-col gap-2">
          <h1 className="min-w-0 max-w-full font-display text-[22px] leading-tight tracking-[-0.02em] text-fg sm:text-[26px]">
            <TruncatedText>{kb.name}</TruncatedText>
          </h1>
          {kb.description && <p className="max-w-[72ch] text-[14px] text-fg-2">{kb.description}</p>}
          <div className="flex flex-wrap items-center gap-2">
            <KbStatusBadge status={kb.status} />
            {kb.attachable ? <Badge tone="accent">Can be attached</Badge> : <Badge>Not attachable yet</Badge>}
            <span className="flex items-center gap-0.5 rounded-inline bg-surface-2 py-0.5 pl-2 pr-0.5">
              <span className="font-mono text-[12px] text-fg-3">{kb.id}</span>
              <CopyButton value={kb.id} label="Copy knowledge base ID" className="size-6" />
            </span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Menu>
            <MenuTrigger asChild>
              <Button icon={<MoreHorizontal aria-hidden />} aria-label="More actions">
                More
              </Button>
            </MenuTrigger>
            <MenuContent>
              <MenuItem onSelect={() => setRenaming(true)}>
                <Pencil aria-hidden /> Rename or describe
              </MenuItem>
              <MenuItem danger onSelect={() => setDeletingKb(true)}>
                <Trash2 aria-hidden /> Delete knowledge base
              </MenuItem>
            </MenuContent>
          </Menu>
          <Button icon={<Cloud aria-hidden />} onClick={() => setAddingSource(true)}>
            Add Google Drive source
          </Button>
          <Button variant="primary" icon={<CloudUpload aria-hidden />} onClick={() => setUploadOpen(true)}>
            Upload
          </Button>
        </div>
      </header>

      <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat icon={<FileText />} label="Documents" value={kb.document_count.toLocaleString()} />
        <Stat icon={<CircleCheck />} label="Ready" value={`${kb.ready_count} / ${kb.document_count}`} />
        <Stat icon={<HardDrive />} label="Size" value={formatBytes(kb.total_bytes)} />
        <Stat icon={<Bot />} label="Agents" value={kb.agent_count.toLocaleString()} />
      </div>

      <WorkLayout
        main={
          <Panel
            title="Documents"
            description={
              tab === "archived"
                ? "Archived documents are out of search and are deleted 30 days after archiving."
                : "Newest first. Status updates on its own while documents are processed."
            }
            bodyClassName="p-0"
            actions={
              kb.archived_count > 0 || tab === "archived" ? (
                <Tabs
                  value={tab}
                  onValueChange={(v) => setTab(v as "documents" | "archived")}
                  density="compact"
                  aria-label="Document view"
                  items={[
                    { value: "documents", label: "Documents", count: kb.document_count },
                    { value: "archived", label: "Archived", icon: <Archive />, count: kb.archived_count },
                  ]}
                >
                  {null}
                </Tabs>
              ) : undefined
            }
          >
            {tab === "archived" && archived.isError ? (
              <EmptyState compact icon={<Archive />} title="Archived documents did not load">
                {problemMessage(archived.error, "document")}
              </EmptyState>
            ) : tab === "archived" ? (
              <Table
                columns={columns}
                rows={archived.data?.items}
                rowKey={(d) => d.id}
                loading={archived.isPending}
                skeletonRows={2}
                caption="Archived documents"
                empty={<EmptyState compact icon={<Archive />} title="Nothing archived" />}
              />
            ) : docs.isError ? (
              <EmptyState compact icon={<BookOpenText weight="duotone" />} title="Documents did not load">
                {problemMessage(docs.error, "document")}
              </EmptyState>
            ) : (
              <>
                <Table
                  columns={columns}
                  rows={docs.data?.items}
                  rowKey={(d) => d.id}
                  loading={docs.isPending}
                  skeletonRows={4}
                  caption="Documents"
                  className="hidden md:block"
                  empty={emptyState}
                />
                <ul className="divide-y divide-line md:hidden" aria-label="Documents">
                  {docs.isPending
                    ? [0, 1, 2].map((i) => (
                        <li key={i} className="px-5 py-4">
                          <Skeleton className="h-10 w-full" />
                        </li>
                      ))
                    : docs.data?.items.map((d) => (
                        <li key={d.id} className="flex flex-col gap-2 px-5 py-3">
                          {columns[0]!.cell(d)}
                          <div className="flex items-center justify-between gap-2 pl-11">
                            <span className="font-mono text-[12px] text-fg-3 tnum">{formatBytes(d.file_size)}</span>
                            {columns[columns.length - 1]!.cell(d)}
                          </div>
                        </li>
                      ))}
                </ul>
                {docs.data?.items.length === 0 && <div className="md:hidden">{emptyState}</div>}
              </>
            )}
          </Panel>
        }
        inspector={
          <>
            <Panel
              title="Google Drive sources"
              description="Folders this knowledge base keeps in step with. Calls only search the synced copy."
              icon={<Cloud />}
            >
              {sources.data?.items.length ? (
                <div className="flex flex-col gap-3">
                  {sources.data.items.map((src) => (
                    <SourceCard key={src.id} kbId={kb.id} source={src} />
                  ))}
                </div>
              ) : (
                <div className="flex flex-col items-start gap-2 text-[13px] text-fg-3">
                  <p>Sync a Drive folder instead of uploading files by hand. Edits in Drive show up here on their own.</p>
                  <Button size="sm" icon={<Cloud />} onClick={() => setAddingSource(true)}>
                    Add Google Drive source
                  </Button>
                </div>
              )}
            </Panel>
            <SearchPreviewPanel kbId={kb.id} disabled={!kb.attachable} />
            {kb.processing_count > 0 && (
              <Tooltip content="Large documents can take up to two minutes.">
                <p className="flex items-center gap-2 rounded-panel bg-accent-soft/60 px-4 py-3 text-[13px] text-fg" tabIndex={0}>
                  <RotateCw className="size-4 animate-spin text-accent-text" aria-hidden />
                  {kb.processing_count} {kb.processing_count === 1 ? "document is" : "documents are"} being processed.
                </p>
              </Tooltip>
            )}
          </>
        }
      />

      <UploadDialog
        open={uploadOpen}
        onOpenChange={(o) => {
          setUploadOpen(o);
          if (!o && params.get("upload")) setParams((p) => (p.delete("upload"), p), { replace: true });
        }}
        kbId={kb.id}
        kbName={kb.name}
      />
      <AddDriveSourceDialog open={addingSource} onOpenChange={setAddingSource} kbId={kb.id} kbName={kb.name} />
      <CreateKbDialog open={renaming} onOpenChange={setRenaming} existing={kb} onCreated={() => refresh()} />
      <Dialog
        open={deletingDoc !== null}
        onOpenChange={(o) => !o && !removeDoc.isPending && setDeletingDoc(null)}
        role="alertdialog"
        size="sm"
        icon={<Trash2 />}
        title={`Delete ${deletingDoc?.display_name ?? deletingDoc?.file_name ?? "document"}?`}
        description="Searches stop finding it at once. The file and its passages are removed."
        footer={
          <>
            <Button autoFocus onClick={() => setDeletingDoc(null)} disabled={removeDoc.isPending}>
              Cancel
            </Button>
            <Button variant="danger" pending={removeDoc.isPending} onClick={() => deletingDoc && removeDoc.mutate(deletingDoc)}>
              Delete document
            </Button>
          </>
        }
      />
      <Dialog
        open={deletingKb || inUse !== null}
        onOpenChange={(o) => {
          if (!o && !removeKb.isPending) {
            setDeletingKb(false);
            setInUse(null);
          }
        }}
        role="alertdialog"
        size="sm"
        icon={<Trash2 />}
        title={inUse ? `${kb.name} is attached to agents` : `Delete ${kb.name}?`}
        description={
          inUse
            ? "Deleting detaches it from these agents' drafts. Published versions keep running but find nothing in it."
            : "Its documents and passages are deleted. This cannot be undone."
        }
        footer={
          <>
            <Button
              autoFocus
              onClick={() => {
                setDeletingKb(false);
                setInUse(null);
              }}
              disabled={removeKb.isPending}
            >
              Cancel
            </Button>
            <Button variant="danger" pending={removeKb.isPending} onClick={() => removeKb.mutate(inUse !== null)}>
              {inUse ? "Detach and delete" : "Delete"}
            </Button>
          </>
        }
      >
        {inUse && (
          <ul className="flex flex-col gap-2">
            {inUse.map((a) => (
              <li key={a.agent_id} className="flex items-center gap-2.5 rounded-control bg-surface-2/70 px-3 py-2">
                <Bot className="size-4 text-fg-3" aria-hidden />
                <Link to={agentPath({ id: a.agent_id })} className="link-underline text-[13px] text-fg">
                  {a.agent_name}
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Dialog>
    </div>
  );
}

function PageSkeleton() {
  return (
    <div className="flex flex-col" aria-busy="true" aria-label="Loading knowledge base">
      <Skeleton className="mb-4 h-4 w-24" />
      <Skeleton className="mb-3 h-8 w-72" />
      <Skeleton className="mb-7 h-5 w-56" />
      <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-4">
        {Array.from({ length: 4 }, (_, i) => (
          <Skeleton key={i} className="h-[70px] w-full rounded-panel" />
        ))}
      </div>
      <WorkLayout
        main={<Skeleton className="h-[320px] w-full rounded-panel" />}
        inspector={<Skeleton className="h-[220px] w-full rounded-panel" />}
      />
    </div>
  );
}
