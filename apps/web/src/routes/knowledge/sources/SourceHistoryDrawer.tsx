import { ChevronLeft } from "lucide-react";
import { useState } from "react";
import { useSyncRun, useSyncRuns, type KnowledgeSource, type SyncRun } from "../../../api/knowledge";
import { problemMessage } from "../../../api/problems";
import { Badge, Button, Drawer, Skeleton, type Tone } from "../../../components";
import { timeAgo } from "../../../lib/format";
import { SKIP_REASON } from "../kbStatus";

const STATUS: Record<SyncRun["status"], { label: string; tone: Tone }> = {
  running: { label: "Running", tone: "accent" },
  succeeded: { label: "Done", tone: "success" },
  held: { label: "Held back", tone: "warning" },
  failed: { label: "Failed", tone: "danger" },
};

const TRIGGER: Record<SyncRun["trigger"], string> = {
  first: "First sync",
  scheduled: "Scheduled",
  manual: "Sync now",
  reconnect: "After reconnect",
};

const FAILURE: Record<string, string> = {
  access_lost: "Access to the folder was lost",
  connection_revoked: "Google access was revoked",
  google_unavailable: "Google did not answer",
  source_too_large: "The folder holds more than 5,000 items",
  internal: "Something went wrong on our side",
};

const COUNTS: [keyof SyncRun["counts"], string][] = [
  ["added", "Added"],
  ["updated", "Updated"],
  ["unchanged", "Unchanged"],
  ["renamed", "Renamed"],
  ["archived", "Archived"],
  ["held_back", "Held back"],
  ["skipped", "Skipped"],
  ["failed", "Failed"],
];

function duration(run: SyncRun): string {
  if (!run.finished_at) return "running";
  const s = Math.max(0, Math.round((new Date(run.finished_at).getTime() - new Date(run.started_at).getTime()) / 1000));
  return s < 60 ? `${s} s` : `${Math.round(s / 60)} min`;
}

/** Sync history of one source (022 US5): every run with its trigger, counts and per-file errors. */
export function SourceHistoryDrawer({
  open,
  onOpenChange,
  kbId,
  source,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  kbId: string;
  source: KnowledgeSource;
}) {
  const runs = useSyncRuns(kbId, open ? source.id : undefined);
  const [selected, setSelected] = useState<string | null>(null);
  const run = useSyncRun(kbId, source.id, open ? selected : null);
  return (
    <Drawer
      open={open}
      onOpenChange={(o) => {
        onOpenChange(o);
        if (!o) setSelected(null);
      }}
      title={`Sync history: ${source.root_name}`}
      meta="Runs are kept for 90 days."
      width="md"
    >
      {selected ? (
        <div className="flex flex-col gap-4">
          <Button size="sm" variant="ghost" icon={<ChevronLeft />} onClick={() => setSelected(null)} className="w-fit">
            All runs
          </Button>
          {run.isPending ? (
            <Skeleton className="h-32 w-full" />
          ) : run.isError ? (
            <p className="text-[13px] text-danger-text">{problemMessage(run.error, "sync run")}</p>
          ) : (
            <>
              <RunSummary run={run.data} />
              <h3 className="text-[13px] font-semibold text-fg">Files not imported or failed</h3>
              {run.data.errors.length === 0 ? (
                <p className="text-[13px] text-fg-3">None.</p>
              ) : (
                <ul className="flex flex-col gap-2">
                  {run.data.errors.map((e) => (
                    <li key={e.drive_file_id} className="flex flex-col rounded-control bg-surface-2/60 px-3 py-2 text-[12px]">
                      <span className="text-fg">{e.path ? `${e.path}/${e.name}` : e.name}</span>
                      <span className="text-fg-3">{e.message ?? SKIP_REASON[e.reason]}</span>
                    </li>
                  ))}
                </ul>
              )}
              {run.data.errors_truncated > 0 && <p className="text-[12px] text-fg-3">And {run.data.errors_truncated} more.</p>}
            </>
          )}
        </div>
      ) : runs.isPending ? (
        <Skeleton className="h-40 w-full" />
      ) : runs.isError ? (
        <p className="text-[13px] text-danger-text">{problemMessage(runs.error, "sync run")}</p>
      ) : runs.data.items.length === 0 ? (
        <p className="text-[13px] text-fg-3">No syncs yet.</p>
      ) : (
        <ul className="flex flex-col gap-2" aria-label="Sync runs">
          {runs.data.items.map((r) => (
            <li key={r.id}>
              <button
                type="button"
                onClick={() => setSelected(r.id)}
                className="flex w-full flex-col gap-1 rounded-control border border-line px-3 py-2.5 text-left hover:bg-surface-2"
              >
                <RunSummary run={r} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </Drawer>
  );
}

function RunSummary({ run }: { run: SyncRun }) {
  const status = STATUS[run.status];
  const shown = COUNTS.filter(([key]) => run.counts[key] > 0);
  return (
    <div className="flex flex-col gap-1">
      <span className="flex items-center justify-between gap-2 text-[13px]">
        <span className="text-fg">
          {TRIGGER[run.trigger]} · {timeAgo(run.started_at)} · {duration(run)}
        </span>
        <Badge tone={status.tone}>{status.label}</Badge>
      </span>
      {run.failure_reason && <span className="text-[12px] text-danger-text">{FAILURE[run.failure_reason] ?? run.failure_reason}</span>}
      <span className="text-[12px] text-fg-3">
        {shown.length === 0 ? "No changes" : shown.map(([key, label]) => `${run.counts[key]} ${label.toLowerCase()}`).join(", ")}
      </span>
    </div>
  );
}
