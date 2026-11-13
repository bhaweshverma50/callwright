import { Archive, CircleCheck, CircleDashed, CircleX, LoaderCircle, TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";
import type { DocumentStatus, KnowledgeBase, KnowledgeSource, SourceFileIssue } from "../../api/knowledge";
import { Badge, type Tone } from "../../components";

const KB_STATUS: Record<KnowledgeBase["status"], { label: string; tone: Tone; icon: ReactNode }> = {
  empty: { label: "No documents", tone: "neutral", icon: <CircleDashed /> },
  processing: { label: "Processing", tone: "accent", icon: <LoaderCircle className="animate-spin" /> },
  ready: { label: "Ready", tone: "success", icon: <CircleCheck /> },
  partial: { label: "Partly ready", tone: "warning", icon: <TriangleAlert /> },
  failed: { label: "Failed", tone: "danger", icon: <CircleX /> },
};

export function KbStatusBadge({ status }: { status: KnowledgeBase["status"] }) {
  const s = KB_STATUS[status];
  return (
    <Badge tone={s.tone} icon={s.icon}>
      {s.label}
    </Badge>
  );
}

const DOC_STATUS: Record<DocumentStatus, { label: string; tone: Tone; icon: ReactNode }> = {
  uploaded: { label: "Queued", tone: "neutral", icon: <CircleDashed /> },
  processing: { label: "Processing", tone: "accent", icon: <LoaderCircle className="animate-spin" /> },
  ready: { label: "Ready", tone: "success", icon: <CircleCheck /> },
  failed: { label: "Failed", tone: "danger", icon: <CircleX /> },
  archived: { label: "Archived", tone: "neutral", icon: <Archive /> },
};

export function DocStatusBadge({ status }: { status: DocumentStatus }) {
  const s = DOC_STATUS[status];
  return (
    <Badge tone={s.tone} icon={s.icon}>
      {s.label}
    </Badge>
  );
}

export const ERROR_HELP: Record<string, string> = {
  no_extractable_text: "No text could be read. Scanned pages are not supported; upload a text PDF or a Word file.",
  corrupt_file: "The file could not be read. It may be damaged; export it again and upload the new copy.",
  encrypted_file: "The PDF is password protected. Remove the password and upload it again.",
  embedding_unavailable: "The search index service was unavailable. Retry in a few minutes.",
  too_many_chunks: "The document is too long. Split it into smaller files.",
  internal: "Processing failed. Retry the document.",
};

const SOURCE_STATE: Record<KnowledgeSource["state"], { label: string; tone: Tone; icon: ReactNode }> = {
  pending: { label: "Waiting for first sync", tone: "neutral", icon: <CircleDashed /> },
  syncing: { label: "Syncing", tone: "accent", icon: <LoaderCircle className="animate-spin" /> },
  healthy: { label: "In sync", tone: "success", icon: <CircleCheck /> },
  needs_attention: { label: "Needs attention", tone: "warning", icon: <TriangleAlert /> },
};

export function SourceStateBadge({ state }: { state: KnowledgeSource["state"] }) {
  const s = SOURCE_STATE[state];
  return (
    <Badge tone={s.tone} icon={s.icon}>
      {s.label}
    </Badge>
  );
}

/** Why a Drive file was not imported, in words an operator can act on. */
export const SKIP_REASON: Record<SourceFileIssue["reason"], string> = {
  unsupported_type: "Not a Google Doc, PDF or Word file",
  too_large: "Larger than 20 MB",
  export_too_large: "Google Doc larger than Drive's 10 MB export limit",
  shortcut: "Shortcut to a file outside this folder",
  duplicate: "Same content as another document here",
  kb_full: "Knowledge base is full (200 documents)",
  workspace_storage_full: "Workspace storage is full (1 GB)",
  download_failed: "Could not be read from Drive",
  processing_failed: "Could not be processed",
};

/** Sync intervals the source card offers, in minutes. */
export const SYNC_INTERVALS = [
  { value: "5", label: "Every 5 minutes" },
  { value: "15", label: "Every 15 minutes" },
  { value: "60", label: "Every hour" },
  { value: "360", label: "Every 6 hours" },
  { value: "1440", label: "Every day" },
];
