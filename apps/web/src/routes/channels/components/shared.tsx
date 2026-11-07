import { AlertTriangle, CircleCheck, CircleDashed, Hourglass, LoaderCircle, Plug } from "lucide-react";
import type { ReactNode } from "react";
import type { AgentSummary } from "../../../api/agents";
import { Badge, OnAir, Select, cn, type SelectGroup, type Tone } from "../../../components";

type Status = "provisioning" | "active" | "error" | "draining" | "setup_incomplete";

const STATUS: Record<Status, { tone: Tone; label: string; icon: ReactNode }> = {
  provisioning: { tone: "accent", label: "Setting up", icon: <LoaderCircle className="animate-spin" aria-hidden /> },
  active: { tone: "success", label: "Active", icon: <CircleCheck aria-hidden /> },
  error: { tone: "danger", label: "Setup failed", icon: <AlertTriangle aria-hidden /> },
  draining: { tone: "warning", label: "Deleting when idle", icon: <Hourglass aria-hidden /> },
  setup_incomplete: { tone: "warning", label: "Awaiting verification", icon: <CircleDashed aria-hidden /> },
};

export function ChannelStatusBadge({ status }: { status: Status }) {
  const s = STATUS[status] ?? STATUS.active;
  return (
    <Badge tone={s.tone} icon={s.icon}>
      {s.label}
    </Badge>
  );
}

/** Live calls on a number or channel: the on-air dot when there are any. */
export function ActiveCalls({ count }: { count: number }) {
  if (count > 0) return <OnAir label={`${count} live ${count === 1 ? "call" : "calls"}`} />;
  return <span className="text-[13px] text-fg-3">No live calls</span>;
}

export const NO_AGENT = "none";

/** Agent picker: published agents first; drafts are listed but cannot be chosen (FR-006). */
export function AgentSelect({
  id,
  value,
  onValueChange,
  agents,
  noneLabel,
  disabled,
  invalid,
  describedBy,
  size,
  className,
  "aria-label": ariaLabel,
}: {
  id?: string;
  value: string | null | undefined;
  onValueChange: (agentId: string | null) => void;
  agents: AgentSummary[] | undefined;
  /** Label of the empty choice; omit to require an agent. */
  noneLabel?: string;
  disabled?: boolean;
  invalid?: boolean;
  describedBy?: string;
  size?: "sm" | "md";
  className?: string;
  "aria-label"?: string;
}) {
  const published = (agents ?? []).filter((a) => a.published_version);
  const drafts = (agents ?? []).filter((a) => !a.published_version);
  const groups: SelectGroup[] = [];
  if (noneLabel) groups.push({ label: "", options: [{ value: NO_AGENT, label: noneLabel }] });
  groups.push({
    label: published.length ? "Published agents" : "",
    options: published.map((a) => ({ value: a.id, label: a.name, meta: a.published_version ? `v${a.published_version.version_number}` : undefined })),
  });
  if (drafts.length) {
    groups.push({ label: "Publish these first", options: drafts.map((a) => ({ value: a.id, label: a.name, disabled: true, meta: "draft" })) });
  }
  return (
    <Select
      id={id}
      value={value ?? (noneLabel ? NO_AGENT : undefined)}
      onValueChange={(v) => onValueChange(v === NO_AGENT ? null : v)}
      groups={groups}
      placeholder={agents ? "Choose an agent" : "Loading agents"}
      disabled={disabled}
      invalid={invalid}
      describedBy={describedBy}
      size={size}
      className={className}
      aria-label={ariaLabel}
    />
  );
}

/** Notice shown while the deployment has no SIP service: numbers save but no call reaches them. */
export function TelephonyNotice({ className }: { className?: string }) {
  return (
    <div
      role="note"
      className={cn(
        "flex items-start gap-3 rounded-panel border border-warning/30 bg-warning-soft/60 px-4 py-3 text-[13px] leading-relaxed text-fg-2",
        className,
      )}
    >
      <span className="mt-0.5 grid size-7 shrink-0 place-items-center rounded-control bg-warning-soft text-warning-text [&_svg]:size-4">
        <Plug aria-hidden />
      </span>
      <p>
        <span className="font-medium text-fg">Telephony is not switched on for this deployment yet.</span> Numbers and WhatsApp channels save with
        their agents and settings, but calls only reach them once the SIP service is enabled. Outbound calls wait for it too.
      </p>
    </div>
  );
}
