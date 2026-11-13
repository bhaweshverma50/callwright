import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Archive, Cloud, Folder, HardDrive, History, RefreshCw, Trash2, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { isApiError } from "../../../api/errors";
import { decideHeldArchive, kbKeys, sourceKeys, syncSource, updateSource, useSource, type KnowledgeSource } from "../../../api/knowledge";
import { problemMessage } from "../../../api/problems";
import { Badge, Button, ConfirmDialog, Select, toast } from "../../../components";
import { timeAgo } from "../../../lib/format";
import { BILLING_PATH, CONNECTIONS_PATH } from "../../../lib/paths";
import { SKIP_REASON, SourceStateBadge, SYNC_INTERVALS } from "../kbStatus";
import { RemoveSourceDialog } from "./RemoveSourceDialog";
import { SourceHistoryDrawer } from "./SourceHistoryDrawer";

function lastRunSummary(run: NonNullable<KnowledgeSource["last_run"]>): string {
  if (run.status === "running") return "Running";
  const c = run.counts;
  const parts = [
    c.added && `${c.added} added`,
    c.updated && `${c.updated} updated`,
    c.renamed && `${c.renamed} renamed`,
    c.archived && `${c.archived} archived`,
    c.held_back && `${c.held_back} held back`,
    c.skipped && `${c.skipped} not imported`,
    c.failed && `${c.failed} failed`,
  ].filter(Boolean);
  if (run.status === "failed") return "Failed";
  return parts.length ? parts.join(", ") : "No changes";
}

/** One Google Drive source on a knowledge base (022 US2 to US5). */
export function SourceCard({ kbId, source: s }: { kbId: string; source: KnowledgeSource }) {
  const qc = useQueryClient();
  const detail = useSource(kbId, s.id, s.last_run ? `${s.last_run.id}:${s.last_run.status}` : null);
  const [removing, setRemoving] = useState(false);
  const [history, setHistory] = useState(false);
  const [confirmHeld, setConfirmHeld] = useState(false);
  const refresh = () => {
    qc.invalidateQueries({ queryKey: sourceKeys.list(kbId) });
    qc.invalidateQueries({ queryKey: ["knowledge", "sources", kbId, s.id] });
    qc.invalidateQueries({ queryKey: kbKeys.all });
  };

  const sync = useMutation({
    mutationFn: () => syncSource(kbId, s.id),
    onSuccess: () => {
      refresh();
      toast({ tone: "info", title: "Sync started", description: `${s.root_name} is being checked for changes.` });
    },
    onError: (e) => {
      if (isApiError(e) && e.problem?.code === "sync_running") {
        toast({ tone: "info", title: "Already syncing", description: "A sync of this source is running." });
        refresh();
        return;
      }
      toast({ tone: "error", title: "Sync did not start", description: problemMessage(e, "source") });
    },
  });
  const schedule = useMutation({
    mutationFn: (minutes: number) => updateSource(kbId, s.id, { interval_minutes: minutes }),
    onSuccess: () => refresh(),
    onError: (e) => toast({ tone: "error", title: "Schedule not changed", description: problemMessage(e, "source") }),
  });
  const held = useMutation({
    mutationFn: (decision: "confirm" | "cancel") => decideHeldArchive(kbId, s.id, decision),
    onSuccess: (_r, decision) => {
      setConfirmHeld(false);
      refresh();
      toast({
        tone: "success",
        title: decision === "confirm" ? "Documents archived" : "Archiving cancelled",
        description: decision === "confirm" ? "They can be restored for 30 days." : "The documents stay in search.",
      });
    },
    onError: (e) => toast({ tone: "error", title: "Not applied", description: problemMessage(e, "source") }),
  });

  const running = s.state === "syncing" || s.state === "pending";
  const issues = detail.data?.not_imported ?? [];
  const interval = String(s.interval_minutes);
  const intervals = SYNC_INTERVALS.some((o) => o.value === interval)
    ? SYNC_INTERVALS
    : [...SYNC_INTERVALS, { value: interval, label: `Every ${s.interval_minutes} minutes` }];

  return (
    <section aria-label={`Source ${s.root_name}`} className="flex flex-col gap-3 rounded-panel border border-line bg-surface p-4 shadow-1">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-2.5">
          <span className="mt-0.5 text-fg-3 [&_svg]:size-4">{s.root_kind === "shared_drive" ? <HardDrive /> : <Folder />}</span>
          <div className="flex min-w-0 flex-col gap-0.5">
            <span className="truncate font-medium text-fg">{s.root_name}</span>
            <span className="flex items-center gap-1 truncate text-[12px] text-fg-3">
              <Cloud className="size-3" aria-hidden /> {s.account_email}
              {s.root_kind === "folder" && !s.include_subfolders && " · without subfolders"}
            </span>
          </div>
        </div>
        <SourceStateBadge state={s.state} />
      </div>

      {s.state === "needs_attention" && s.attention_message && (
        <div role="status" className="flex items-start gap-2 rounded-control bg-warning-soft px-3 py-2 text-[13px] text-warning-text">
          <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
          <div className="flex flex-col gap-2">
            <span>{s.attention_message}.</span>
            {s.attention_reason === "mass_archive" && (
              <span className="flex flex-wrap gap-2">
                <Button size="sm" variant="danger" onClick={() => setConfirmHeld(true)}>
                  Archive them
                </Button>
                <Button size="sm" onClick={() => held.mutate("cancel")} pending={held.isPending && held.variables === "cancel"}>
                  Keep them
                </Button>
              </span>
            )}
            {s.attention_reason === "access_lost" && (
              <Link to={CONNECTIONS_PATH} className="link-underline w-fit font-medium">
                Reconnect in Connections
              </Link>
            )}
            {s.attention_reason === "no_credit" && (
              <Link to={BILLING_PATH} className="link-underline w-fit font-medium">
                Add funds
              </Link>
            )}
          </div>
        </div>
      )}

      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-[12px]">
        <dt className="text-fg-3">Documents</dt>
        <dd className="text-right font-mono text-fg tnum">{s.document_count}</dd>
        <dt className="text-fg-3">Last synced</dt>
        <dd className="text-right text-fg">{s.last_success_at ? timeAgo(s.last_success_at) : "Not yet"}</dd>
        {s.last_run && (
          <>
            <dt className="text-fg-3">Last run</dt>
            <dd className="text-right text-fg">{lastRunSummary(s.last_run)}</dd>
          </>
        )}
      </dl>

      {issues.length > 0 && (
        <details className="rounded-control bg-surface-2/60 px-3 py-2 text-[12px]">
          <summary className="cursor-pointer text-fg-2">Not imported ({issues.length})</summary>
          <ul className="mt-2 flex flex-col gap-1.5">
            {issues.map((i) => (
              <li key={i.drive_file_id} className="flex flex-col">
                <span className="truncate text-fg">{i.path ? `${i.path}/${i.name}` : i.name}</span>
                <span className="text-fg-3">{SKIP_REASON[i.reason]}</span>
              </li>
            ))}
          </ul>
        </details>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" icon={<RefreshCw />} onClick={() => sync.mutate()} pending={sync.isPending} disabled={running}>
          {running ? "Syncing" : "Sync now"}
        </Button>
        <Select
          size="sm"
          aria-label="Sync schedule"
          value={interval}
          onValueChange={(v) => schedule.mutate(Number(v))}
          options={intervals}
          className="w-[160px]"
        />
        <Button size="sm" variant="ghost" icon={<History />} onClick={() => setHistory(true)}>
          History
        </Button>
        <Button size="sm" variant="ghost" icon={<Trash2 />} aria-label={`Remove source ${s.root_name}`} onClick={() => setRemoving(true)}>
          Remove
        </Button>
      </div>

      <RemoveSourceDialog open={removing} onOpenChange={setRemoving} kbId={kbId} source={s} onRemoved={refresh} />
      <SourceHistoryDrawer open={history} onOpenChange={setHistory} kbId={kbId} source={s} />
      <ConfirmDialog
        open={confirmHeld}
        onOpenChange={setConfirmHeld}
        icon={<Archive />}
        title={`Archive ${s.held_archive?.would_archive ?? 0} documents?`}
        description="Their files are no longer in the Drive folder. Archived documents leave search and can be restored for 30 days."
        confirmLabel="Archive documents"
        tone="danger"
        pending={held.isPending && held.variables === "confirm"}
        onConfirm={() => held.mutate("confirm")}
      />
      {s.held_archive && <Badge tone="warning">{s.held_archive.would_archive} held back</Badge>}
    </section>
  );
}
