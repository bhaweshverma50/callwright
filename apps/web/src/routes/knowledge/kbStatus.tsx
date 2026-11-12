import { Archive, CircleCheck, CircleDashed, CircleX, LoaderCircle, TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";
import type { DocumentStatus, KnowledgeBase } from "../../api/knowledge";
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
