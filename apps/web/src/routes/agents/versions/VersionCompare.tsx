import { ArrowRight, Equal, Minus, PencilLine, Plus } from "lucide-react";
import { useMemo } from "react";
import { useVersionDiff, type VersionChange, type VersionSummary } from "../../../api/agents";
import { problemMessage } from "../../../api/problems";
import { Badge, Select, Skeleton, TruncatedText } from "../../../components";
import { DiffView } from "./DiffView";
import { lineDiff } from "./lineDiff";
import { formatValue, isLongText, labelFor } from "./versionLabels";

const OPS = {
  add: { label: "Added", tone: "success" as const, icon: <Plus /> },
  remove: { label: "Removed", tone: "danger" as const, icon: <Minus /> },
  replace: { label: "Changed", tone: "accent" as const, icon: <PencilLine /> },
};

/**
 * Compare a version with the draft or another version (T061, US3.2): one row per changed field
 * with its readable name, old and new values, and a line-by-line difference for long text. List
 * items are matched by key on the server, so reordering never shows as a change.
 */
export function VersionCompare({
  agentId,
  version,
  against,
  versions,
  onAgainstChange,
}: {
  agentId: string;
  version: VersionSummary;
  against: string;
  versions: VersionSummary[];
  onAgainstChange: (v: string) => void;
}) {
  const diff = useVersionDiff(agentId, version.id, against);
  const fromLabel = against === "draft" ? "Draft" : `Version ${versions.find((v) => v.id === against)?.version_number ?? ""}`;
  const toLabel = `Version ${version.version_number}`;
  const options = [
    { value: "draft", label: "The current draft" },
    ...versions
      .filter((v) => v.id !== version.id)
      .map((v) => ({ value: v.id, label: `Version ${v.version_number}${v.is_published ? " (live)" : ""}` })),
  ];
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-2 rounded-panel bg-surface-2/60 p-3.5 sm:flex-row sm:items-center">
        <span className="shrink-0 text-[13px] text-fg-2">Compare {toLabel} with</span>
        <Select aria-label="Compare with" className="sm:w-[220px]" size="sm" value={against} onValueChange={onAgainstChange} options={options} />
      </div>
      {diff.isPending ? (
        <div className="flex flex-col gap-2" aria-label="Loading changes">
          {Array.from({ length: 4 }, (_, i) => (
            <Skeleton key={i} className="h-14 w-full rounded-panel" />
          ))}
        </div>
      ) : diff.isError ? (
        <p className="text-[13px] text-danger-text">{problemMessage(diff.error, "version")}</p>
      ) : diff.data.changes.length === 0 ? (
        <div className="flex items-center gap-3 rounded-panel border border-line px-4 py-5 text-[13.5px] text-fg-2">
          <Equal className="size-4 text-fg-3" aria-hidden /> {toLabel} and {fromLabel.toLowerCase() === "draft" ? "the draft" : fromLabel} are the
          same.
        </div>
      ) : (
        <>
          <p className="text-[12.5px] text-fg-3">
            {diff.data.changes.length} {diff.data.changes.length === 1 ? "change" : "changes"} from{" "}
            {fromLabel.toLowerCase() === "draft" ? "the draft" : fromLabel} to {toLabel}.
          </p>
          <ul className="flex flex-col gap-2.5">
            {diff.data.changes.map((c) => (
              <ChangeRow key={c.path} change={c} fromLabel={fromLabel} toLabel={toLabel} />
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

function ChangeRow({ change, fromLabel, toLabel }: { change: VersionChange; fromLabel: string; toLabel: string }) {
  const op = OPS[change.op];
  const long = isLongText(change.path) && typeof (change.old ?? "") === "string" && typeof (change.new ?? "") === "string";
  const lines = useMemo(() => (long ? lineDiff(String(change.old ?? ""), String(change.new ?? "")) : null), [long, change.old, change.new]);
  return (
    <li className="overflow-hidden rounded-panel border border-line bg-surface">
      <div className="flex items-center justify-between gap-3 px-4 py-2.5">
        <span className="min-w-0 text-[13.5px] font-medium text-fg">
          <TruncatedText>{labelFor(change.path)}</TruncatedText>
        </span>
        <Badge tone={op.tone} icon={op.icon}>
          {op.label}
        </Badge>
      </div>
      {lines ? (
        <div className="max-h-[320px] overflow-y-auto border-t border-line">
          <DiffView lines={lines} />
        </div>
      ) : (
        <div className="grid grid-cols-[minmax(0,1fr)] gap-2 border-t border-line px-4 py-3 text-[13px] sm:grid-cols-[minmax(0,1fr)_16px_minmax(0,1fr)] sm:items-start">
          <div className="flex min-w-0 flex-col gap-0.5">
            <span className="text-[11.5px] text-fg-3">{fromLabel}</span>
            <span className="min-w-0 break-words text-fg-2">{change.op === "add" ? "None" : formatValue(change.path, change.old)}</span>
          </div>
          <ArrowRight className="mt-4 hidden size-4 text-fg-3 sm:block" aria-hidden />
          <div className="flex min-w-0 flex-col gap-0.5">
            <span className="text-[11.5px] text-fg-3">{toLabel}</span>
            <span className="min-w-0 break-words font-medium text-fg">{change.op === "remove" ? "None" : formatValue(change.path, change.new)}</span>
          </div>
        </div>
      )}
    </li>
  );
}
