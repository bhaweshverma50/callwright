import { useQueryClient } from "@tanstack/react-query";
import { CircleAlert, CloudUpload, Copy, FileText, Info, LoaderCircle, RefreshCw, Upload, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useRef, useState, type DragEvent } from "react";
import {
  ACCEPT,
  MAX_FILE_BYTES,
  checkDuplicate,
  formatBytes,
  sha256Hex,
  uploadDocument,
  type DuplicateMatch,
  type DuplicateVerdict,
} from "../../api/knowledge";
import { problemMessage } from "../../api/problems";
import { isApiError } from "../../api/errors";
import { Button, Dialog, Field, IconButton, Input, Segmented, cn, toast } from "../../components";

const TYPES = /\.(pdf|docx)$/i;

export function fileProblem(file: File): string | null {
  if (!TYPES.test(file.name)) return "Only PDF and Word (.docx) files can be uploaded.";
  if (file.size > MAX_FILE_BYTES) return `This file is ${formatBytes(file.size)}; the limit is 20 MB.`;
  if (file.size === 0) return "This file is empty.";
  return null;
}

type Check = { state: "idle" } | { state: "checking" } | { state: "done"; verdict: DuplicateVerdict; matches: DuplicateMatch[] } | { state: "error" };

/**
 * Upload one document (T067, T098): PDF or DOCX up to 20 MB, checked in the browser first; the
 * SHA-256 is computed locally so a duplicate is caught before the file is sent. Same content in
 * this knowledge base is refused; elsewhere, or a file with the same name, asks what to do.
 */
export function UploadDialog({
  open,
  onOpenChange,
  kbId,
  kbName,
  onUploaded,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  kbId: string;
  kbName: string;
  onUploaded?: () => void;
}) {
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [check, setCheck] = useState<Check>({ state: "idle" });
  const [displayName, setDisplayName] = useState("");
  const [sameName, setSameName] = useState<"replace" | "keep">("replace");
  const [over, setOver] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const abort = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!open) {
      setFile(null);
      setProblem(null);
      setCheck({ state: "idle" });
      setDisplayName("");
      setProgress(null);
      setFailure(null);
      abort.current?.abort();
    }
  }, [open]);

  const choose = async (f: File | undefined) => {
    if (!f) return;
    setFailure(null);
    const p = fileProblem(f);
    setFile(f);
    setProblem(p);
    setCheck({ state: "idle" });
    if (p) return;
    setCheck({ state: "checking" });
    try {
      const sha = await sha256Hex(f);
      const res = await checkDuplicate(kbId, f, sha);
      setCheck({ state: "done", verdict: res.verdict, matches: res.matches });
    } catch {
      setCheck({ state: "error" });
    }
  };

  const verdict = check.state === "done" ? check.verdict : null;
  const blocked = verdict === "blocked_same_kb";
  const nameMatch = check.state === "done" ? check.matches.find((m) => m.reason === "same_name" && m.kb_id === kbId) : undefined;
  const elsewhere = check.state === "done" ? check.matches.filter((m) => m.reason === "same_content" && m.kb_id !== kbId) : [];
  const uploading = progress !== null;
  const canUpload = Boolean(file) && !problem && !blocked && check.state !== "checking" && !uploading;

  const upload = async () => {
    if (!file) return;
    setFailure(null);
    setProgress(0);
    abort.current = new AbortController();
    try {
      await uploadDocument(kbId, file, {
        displayName,
        replaceDocId: verdict === "warn_same_name" && sameName === "replace" ? nameMatch?.doc_id : undefined,
        acknowledgeDuplicate: elsewhere.length > 0,
        onProgress: setProgress,
        signal: abort.current.signal,
      });
      void qc.invalidateQueries({ queryKey: ["knowledge"] });
      toast({
        tone: "success",
        title: "Uploaded",
        description: `${displayName.trim() || file.name} is being processed. It becomes searchable in a minute or two.`,
      });
      onUploaded?.();
      onOpenChange(false);
    } catch (e) {
      setProgress(null);
      if (isApiError(e) && e.status === 413) setFailure("This file is larger than 20 MB.");
      else if (isApiError(e) && e.status === 415) setFailure("This is not a PDF or Word document, whatever its name says.");
      else if (isApiError(e) && e.code === "quota_exceeded") setFailure(e.problem.detail ?? "A storage limit was reached.");
      else if (isApiError(e) && e.code === "duplicate_document") setFailure("This knowledge base already has a document with the same content.");
      else setFailure(problemMessage(e, "knowledge base"));
    }
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setOver(false);
    void choose(e.dataTransfer.files[0]);
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => !uploading && onOpenChange(o)}
      icon={<CloudUpload />}
      title={`Upload to ${kbName}`}
      description="PDF or Word (.docx), up to 20 MB. Text is read, split into passages and indexed for search."
      footer={
        <>
          <Button onClick={() => onOpenChange(false)} disabled={uploading}>
            Cancel
          </Button>
          <Button variant="primary" icon={<Upload aria-hidden />} disabled={!canUpload} pending={uploading} onClick={() => void upload()}>
            {verdict === "warn_same_name" && sameName === "replace" ? "Upload and replace" : "Upload"}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <input
          ref={input}
          type="file"
          accept={ACCEPT}
          className="sr-only"
          tabIndex={-1}
          aria-hidden
          onChange={(e) => {
            void choose(e.target.files?.[0]);
            e.target.value = "";
          }}
        />
        {!file ? (
          <button
            type="button"
            onClick={() => input.current?.click()}
            onDragOver={(e) => {
              e.preventDefault();
              setOver(true);
            }}
            onDragLeave={() => setOver(false)}
            onDrop={onDrop}
            className={cn(
              "group relative flex flex-col items-center gap-3 overflow-hidden rounded-panel border border-dashed px-6 py-9 text-center transition-[border-color,background-color,transform] duration-200",
              over
                ? "scale-[1.01] border-accent bg-accent-soft/50"
                : "border-line-strong bg-surface-2/50 hover:border-accent/60 hover:bg-accent-soft/25",
              "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
            )}
          >
            <div
              aria-hidden
              className="glow-backdrop pointer-events-none absolute inset-0 opacity-0 transition-opacity duration-300 group-hover:opacity-60"
            />
            <span className="relative grid size-12 place-items-center rounded-panel grad-action text-white shadow-glow transition-transform duration-200 group-hover:-translate-y-0.5 [&_svg]:size-6">
              <CloudUpload aria-hidden />
            </span>
            <span className="relative flex flex-col gap-0.5">
              <span className="text-[14px] font-medium text-fg">Drop a file here, or choose one</span>
              <span className="text-[12.5px] text-fg-3">PDF or DOCX, up to 20 MB</span>
            </span>
          </button>
        ) : (
          <div className="flex min-w-0 items-center gap-3 rounded-panel border border-line bg-surface px-3.5 py-3 shadow-1">
            <span className="grid size-10 shrink-0 place-items-center rounded-control bg-accent-soft text-accent-text [&_svg]:size-5">
              <FileText aria-hidden />
            </span>
            <span className="flex min-w-0 flex-1 flex-col">
              <span className="truncate text-[13.5px] font-medium text-fg">{file.name}</span>
              <span className="flex items-center gap-1.5 text-[12px] text-fg-3">
                {formatBytes(file.size)}
                {check.state === "checking" && (
                  <>
                    <LoaderCircle className="size-3 animate-spin" aria-hidden /> Checking for duplicates
                  </>
                )}
              </span>
            </span>
            {!uploading && (
              <IconButton label="Choose another file" className="size-8" onClick={() => setFile(null)}>
                <X className="size-4" aria-hidden />
              </IconButton>
            )}
          </div>
        )}

        <AnimatePresence initial={false}>
          {(problem || failure || blocked) && (
            <motion.p
              key="problem"
              role="alert"
              initial={{ opacity: 0, y: -4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              className="flex items-start gap-2 rounded-control bg-danger-soft px-3 py-2.5 text-[13px] text-danger-text"
            >
              <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
              {problem ??
                failure ??
                `Already here as ${check.state === "done" ? (check.matches.find((m) => m.kb_id === kbId)?.file_name ?? "another document") : ""}.`}
            </motion.p>
          )}
          {!blocked && elsewhere.length > 0 && (
            <motion.p
              key="elsewhere"
              initial={{ opacity: 0, y: -4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              className="flex items-start gap-2 rounded-control bg-warning-soft px-3 py-2.5 text-[13px] text-warning-text"
            >
              <Copy className="mt-0.5 size-4 shrink-0" aria-hidden />
              The same document is already in {elsewhere.map((m) => m.kb_name).join(", ")}. Uploading keeps a copy here too.
            </motion.p>
          )}
          {verdict === "warn_same_name" && nameMatch && (
            <motion.div
              key="same-name"
              initial={{ opacity: 0, y: -4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              className="flex flex-col gap-2.5 rounded-panel bg-surface-2/70 p-3.5"
            >
              <p className="flex items-start gap-2 text-[13px] text-fg">
                <Info className="mt-0.5 size-4 shrink-0 text-accent-text" aria-hidden />
                {nameMatch.file_name} is already here with different content.
              </p>
              <Segmented
                className="w-fit self-start"
                aria-label="What to do with the existing document"
                size="sm"
                value={sameName}
                onValueChange={setSameName}
                options={[
                  { value: "replace", label: "Replace it", icon: <RefreshCw aria-hidden /> },
                  { value: "keep", label: "Keep both", icon: <Copy aria-hidden /> },
                ]}
              />
              {sameName === "replace" && <p className="text-[12.5px] text-fg-3">The old version stays searchable until the new one is ready.</p>}
            </motion.div>
          )}
        </AnimatePresence>

        <Field label="Display name" hint="Optional. Shown in lists and cited to callers; defaults to the file name.">
          {({ id, describedBy }) => (
            <Input
              id={id}
              maxLength={255}
              aria-describedby={describedBy}
              placeholder={file?.name ?? "Refund policy 2026"}
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
            />
          )}
        </Field>

        {uploading && (
          <div className="flex flex-col gap-1.5" aria-live="polite">
            <div className="flex justify-between text-[12.5px] text-fg-2">
              <span>Uploading</span>
              <span className="font-mono tnum">{Math.round((progress ?? 0) * 100)}%</span>
            </div>
            <div
              className="h-2 overflow-hidden rounded-full bg-surface-3"
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.round((progress ?? 0) * 100)}
            >
              <motion.div
                className="h-full rounded-full grad-action"
                initial={{ width: 0 }}
                animate={{ width: `${Math.max(4, (progress ?? 0) * 100)}%` }}
                transition={{ ease: "easeOut" }}
              />
            </div>
          </div>
        )}
      </div>
    </Dialog>
  );
}
