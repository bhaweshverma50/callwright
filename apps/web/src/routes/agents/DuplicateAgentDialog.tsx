import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, Info, Minus } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { agentChanged, type AgentSummary, duplicateAgent, useAgents, useAgentVersions } from "../../api/agents";
import { problemMessage } from "../../api/problems";
import { Button, Dialog, Field, Input, Select, Skeleton, toast } from "../../components";
import { agentPath } from "../../lib/paths";
import { timeAgo } from "../../lib/format";
import { AGENT_TYPES } from "./agentType";
import { idempotencyKey } from "../../lib/idempotency";

const DRAFT = "draft";
const KEEPS = ["Prompt, greeting and variables", "Model, voice, speech and call settings", "Tools and knowledge bases, linked to the same ones"];
const DROPS = ["Version history and live status (the copy starts at version 1, unpublished)", "Phone numbers, WhatsApp and campaigns"];

/**
 * Duplicate an agent (FR-020, FR-038). Opened from an agent's menu with that agent chosen, or from
 * "a copy of an existing agent" with a picker. Pick any saved version (default: the current
 * draft), name the copy, see what carries over, then the copy opens in the editor.
 */
export function DuplicateAgentDialog({
  open,
  onOpenChange,
  agent,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  /** The agent to copy; null shows a picker. */
  agent: AgentSummary | null;
}) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  // ponytail: the picker lists the 24 most recently edited agents; add search here past that.
  const picker = useAgents("", null, 1, { enabled: open && !agent });
  const [pickedId, setPickedId] = useState<string | null>(null);
  const source = agent ?? picker.data?.items.find((a) => a.id === pickedId) ?? picker.data?.items[0] ?? null;
  const versions = useAgentVersions(source?.id, open);
  const [versionId, setVersionId] = useState(DRAFT);
  const [name, setName] = useState<string | null>(null);
  // One key per dialog opening, so a double click or a retry after a lost response makes one copy.
  const key = useRef(idempotencyKey());

  useEffect(() => {
    if (!open) return;
    key.current = idempotencyKey();
    setPickedId(null);
    setVersionId(DRAFT);
    setName(null);
  }, [open, agent?.id]);

  const copyName = name ?? (source ? `${source.name.slice(0, 73).trimEnd()} (copy)` : "");
  const nameError = name !== null && !name.trim() ? "Name the copy" : null;

  const duplicate = useMutation({
    mutationFn: () => duplicateAgent(source!.id, key.current, { name: copyName.trim(), ...(versionId !== DRAFT && { version_id: versionId }) }),
    onSuccess: (copy) => {
      agentChanged(qc, copy);
      onOpenChange(false);
      toast({ tone: "success", title: "Agent duplicated", description: `${copy.name} starts at version 1 and is not published.` });
      navigate(agentPath(copy));
    },
    onError: (e) => toast({ tone: "error", title: "Not duplicated", description: problemMessage(e, "agent") }),
  });

  const saved = (versions.data?.items ?? []).filter((v) => v.source !== "test");
  const versionOptions = [
    { value: DRAFT, label: "Current draft", meta: "latest" },
    ...saved.map((v) => ({
      value: v.id,
      label: `Version ${v.version_number}${v.is_published ? " · live" : ""}`,
      meta: timeAgo(v.created_at),
    })),
  ];

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => !duplicate.isPending && onOpenChange(o)}
      icon={<Copy />}
      title={agent ? `Duplicate ${agent.name}` : "Duplicate an agent"}
      description="The copy opens in the editor as a new agent. The original and its live version stay as they are."
      footer={
        <>
          <Button onClick={() => onOpenChange(false)} disabled={duplicate.isPending}>
            Cancel
          </Button>
          <Button variant="primary" pending={duplicate.isPending} disabled={!source || !copyName.trim()} onClick={() => duplicate.mutate()}>
            Duplicate and open
          </Button>
        </>
      }
    >
      <form
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault();
          if (source && copyName.trim()) duplicate.mutate();
        }}
      >
        <div className="grid gap-4 sm:grid-cols-2">
          {!agent && (
            <Field label="Agent">
              {({ id, describedBy }) =>
                picker.data ? (
                  <Select
                    id={id}
                    describedBy={describedBy}
                    value={source?.id ?? ""}
                    onValueChange={(v) => {
                      setPickedId(v);
                      setVersionId(DRAFT);
                      setName(null);
                    }}
                    options={picker.data.items.map((a) => ({
                      value: a.id,
                      label: a.name,
                      meta: a.type === "flow" ? AGENT_TYPES.flow.label : undefined,
                    }))}
                    placeholder={picker.data.items.length ? "Choose an agent" : "No agents yet"}
                  />
                ) : (
                  <Skeleton className="h-9 w-full" />
                )
              }
            </Field>
          )}
          <Field label="Version to copy" className={agent ? "sm:col-span-2" : undefined}>
            {({ id, describedBy }) =>
              versions.isPending && source ? (
                <Skeleton className="h-9 w-full" />
              ) : (
                <Select id={id} describedBy={describedBy} value={versionId} onValueChange={setVersionId} options={versionOptions} />
              )
            }
          </Field>
        </div>
        <Field label="Name" error={nameError}>
          {({ id, describedBy, invalid }) => (
            <Input
              id={id}
              maxLength={80}
              value={copyName}
              onChange={(e) => setName(e.target.value)}
              aria-describedby={describedBy}
              aria-invalid={invalid || undefined}
            />
          )}
        </Field>
        <div className="grid gap-4 rounded-panel border border-line bg-surface-2/50 px-4 py-3 sm:grid-cols-2">
          <List title="The copy keeps" items={KEEPS} icon={<Check className="text-success-text" />} />
          <List title="Not copied" items={DROPS} icon={<Minus className="text-fg-3" />} />
        </div>
        <p className="flex items-start gap-2 rounded-control bg-warning-soft px-3 py-2 text-[13px] leading-relaxed text-warning-text">
          <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          Tools and webhooks call the same endpoints as the original. Check them before you publish the copy.
        </p>
        <button type="submit" hidden />
      </form>
    </Dialog>
  );
}

function List({ title, items, icon }: { title: string; items: string[]; icon: React.ReactNode }) {
  return (
    <div>
      <p className="text-[13px] font-medium text-fg">{title}</p>
      <ul className="mt-2 flex flex-col gap-1.5">
        {items.map((t) => (
          <li key={t} className="flex items-start gap-2 text-[13px] leading-snug text-fg-2 [&_svg]:mt-0.5 [&_svg]:size-3.5 [&_svg]:shrink-0">
            {icon}
            {t}
          </li>
        ))}
      </ul>
    </div>
  );
}
