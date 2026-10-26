import { ArrowRight, Equal, Minus, PencilLine, Plus } from "lucide-react";
import { useMemo } from "react";
import { useVersionDiff, type VersionChange, type VersionSummary } from "../../../api/agents";
import { problemMessage } from "../../../api/problems";
import { Badge, Select, Skeleton, TruncatedText } from "../../../components";
import { DiffView } from "./DiffView";
import { lineDiff } from "./lineDiff";
import { formatValue, isLongText, labelFor, objectFields, readableChanges } from "./versionLabels";

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
  const readable = useMemo(() => readableChanges(diff.data?.changes ?? []), [diff.data]);
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
      ) : readable.changes.length === 0 ? (
        <div className="flex items-center gap-3 rounded-panel border border-line px-4 py-5 text-[13.5px] text-fg-2">
          <Equal className="size-4 text-fg-3" aria-hidden /> {toLabel} and {fromLabel.toLowerCase() === "draft" ? "the draft" : fromLabel} are the
          same.
        </div>
      ) : (
        <>
          <p className="text-[12.5px] text-fg-3">
            {readable.changes.length} {readable.changes.length === 1 ? "change" : "changes"} from{" "}
            {fromLabel.toLowerCase() === "draft" ? "the draft" : fromLabel} to {toLabel}.
          </p>
          <ul className="flex flex-col gap-2.5">
            {readable.changes.map((c) => (
              <ChangeRow key={c.path} change={c} names={readable.names} fromLabel={fromLabel} toLabel={toLabel} />
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

function ChangeRow({
  change,
  names,
  fromLabel,
  toLabel,
}: {
  change: VersionChange;
  names: ReadonlyMap<string, string>;
  fromLabel: string;
  toLabel: string;
}) {
  const op = OPS[change.op];
  const long = isLongText(change.path) && typeof (change.old ?? "") === "string" && typeof (change.new ?? "") === "string";
  const lines = useMemo(() => (long ? lineDiff(String(change.old ?? ""), String(change.new ?? "")) : null), [long, change.old, change.new]);
  return (
    <li className="overflow-hidden rounded-panel border border-line bg-surface">
      <div className="flex items-center justify-between gap-3 px-4 py-2.5">
        <span className="min-w-0 text-[13.5px] font-medium text-fg">
          <TruncatedText>{labelFor(change.path, names)}</TruncatedText>
        </span>
        <Badge tone={op.tone} icon={op.icon}>
          {op.label}
        </Badge>
      </div>
      {lines ? (
        <div className="max-h-[320px] overflow-y-auto border-t border-line">
          <DiffView lines={lines} />
        </div>
      ) : change.op !== "replace" ? (
        <div className="flex flex-col gap-1.5 border-t border-line px-4 py-3 text-[13px]">
          <span className="text-[11.5px] text-fg-3">
            {change.op === "add"
              ? `In ${toLabel}, not in ${fromLabel.toLowerCase() === "draft" ? "the draft" : fromLabel}`
              : `In ${fromLabel}, not in ${toLabel}`}
          </span>
          <ValueView path={change.path} value={change.op === "add" ? change.new : change.old} strong={change.op === "add"} />
        </div>
      ) : (
        <div className="grid grid-cols-[minmax(0,1fr)] gap-2 border-t border-line px-4 py-3 text-[13px] sm:grid-cols-[minmax(0,1fr)_16px_minmax(0,1fr)] sm:items-start">
          <div className="flex min-w-0 flex-col gap-0.5">
            <span className="text-[11.5px] text-fg-3">{fromLabel}</span>
            <ValueView path={change.path} value={change.old} />
          </div>
          <ArrowRight className="mt-4 hidden size-4 text-fg-3 sm:block" aria-hidden />
          <div className="flex min-w-0 flex-col gap-0.5">
            <span className="text-[11.5px] text-fg-3">{toLabel}</span>
            <ValueView path={change.path} value={change.new} strong />
          </div>
        </div>
      )}
    </li>
  );
}

/** Shapes ``formatValue`` already reads well (model, variable, word, sound). */
const isPlainShape = (o: Record<string, unknown>) =>
  ("provider" in o && "model" in o) || "word" in o || "kind" in o || ("name" in o && "default" in o);

/** A value in compare: text as people read it, objects as a short list of fields, never JSON. */
function ValueView({ path, value, strong = false }: { path: string; value: unknown; strong?: boolean }) {
  const tone = strong ? "font-medium text-fg" : "text-fg-2";
  if (value && typeof value === "object" && !Array.isArray(value) && !isPlainShape(value as Record<string, unknown>)) {
    const fields = objectFields(path, value as Record<string, unknown>);
    return (
      <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1">
        {fields.map((f) => (
          <div key={f.label} className="contents">
            <dt className="text-fg-3">{f.label}</dt>
            <dd className={`min-w-0 break-words ${tone}`}>{f.value}</dd>
          </div>
        ))}
      </dl>
    );
  }
  const text = Array.isArray(value)
    ? value.map((v) => (v && typeof v === "object" ? formatValue(path, v) : String(v))).join(", ") || "Not set"
    : value === null || value === undefined || value === ""
      ? "Not set"
      : formatValue(path, value);
  return <span className={`min-w-0 break-words ${tone}`}>{text}</span>;
}
