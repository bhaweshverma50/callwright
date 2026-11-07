import { ClipboardText } from "@phosphor-icons/react";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Cpu, Pencil, Plus, Trash2 } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";
import { Link } from "react-router";
import type { AgentConfig } from "../../../api/agents";
import { problemMessage } from "../../../api/problems";
import { deleteVariable, qualityKeys, reorderVariables, useAnalysisVariables, type AnalysisVariable } from "../../../api/quality";
import { Badge, Button, ConfirmDialog, EmptyState, IconButton, Skeleton, toast } from "../../../components";
import { TabHeader } from "../tools/TabHeader";
import { AddVariableDialog, TYPE_ICONS, TYPE_LABELS } from "./AddVariableDialog";
import { operationExtensions } from "../../../lib/contract.gen";
import { agentEditPath } from "../../../lib/paths";

export const MAX_VARIABLES = operationExtensions["POST /agents/{agent_id}/analysis-variables"]["x-max-per-agent"];

function modelLabel(config: AgentConfig): { label: string; own: boolean } {
  const c = config as AgentConfig & { advanced?: { analysis_model?: { provider: string; model: string } | null }; llm?: { model?: string } };
  const own = c.advanced?.analysis_model;
  if (own) return { label: own.model, own: true };
  return { label: c.llm?.model ?? "the agent's model", own: false };
}

/**
 * Post-call analysis variables (US1, T023): every call gets a summary and sentiment; these typed
 * fields are extracted on top, in this order. Variables are per agent, not per version, so
 * changes apply to calls that end from now on without publishing.
 */
export function AnalysisVariablesEditor({
  agentId,
  config,
  showModelLink = true,
}: {
  agentId: string;
  config: AgentConfig;
  showModelLink?: boolean;
}) {
  const qc = useQueryClient();
  const vars = useAnalysisVariables(agentId);
  const [editing, setEditing] = useState<{ open: boolean; variable: AnalysisVariable | null }>({ open: false, variable: null });
  const [removing, setRemoving] = useState<AnalysisVariable | null>(null);
  const [busy, setBusy] = useState(false);
  const items = vars.data ?? [];
  const model = modelLabel(config);
  const full = items.length >= MAX_VARIABLES;

  const move = async (index: number, by: -1 | 1) => {
    const next = [...items];
    const [moved] = next.splice(index, 1);
    next.splice(index + by, 0, moved!);
    qc.setQueryData(qualityKeys.variables(agentId), next);
    try {
      await reorderVariables(
        agentId,
        next.map((v) => v.id),
      );
    } catch (e) {
      toast({ tone: "error", title: "Could not reorder", description: problemMessage(e, "variable") });
    }
    await qc.invalidateQueries({ queryKey: qualityKeys.variables(agentId) });
  };

  const remove = async () => {
    if (!removing) return;
    setBusy(true);
    try {
      await deleteVariable(removing.id);
      toast({ title: `Removed ${removing.name}`, description: "Earlier calls keep the values they captured." });
      setRemoving(null);
      await qc.invalidateQueries({ queryKey: qualityKeys.variables(agentId) });
    } catch (e) {
      toast({ tone: "error", title: "Could not remove the variable", description: problemMessage(e, "variable") });
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="rounded-panel border border-line bg-surface shadow-1" aria-labelledby="analysis-vars-h">
      <TabHeader
        icon={<ClipboardText weight="duotone" aria-hidden />}
        title="Post-call analysis"
        description="Every call gets a summary and the caller's sentiment. Variables pull structured answers out of each call."
        actions={
          <Button
            size="sm"
            variant="primary"
            icon={<Plus aria-hidden />}
            disabled={full}
            title={full ? "Up to 25 variables per agent" : undefined}
            onClick={() => setEditing({ open: true, variable: null })}
          >
            Add variable
          </Button>
        }
      />
      <h3 id="analysis-vars-h" className="sr-only">
        Analysis variables
      </h3>
      <div className="flex flex-wrap items-center gap-2 border-b border-line bg-surface-2/40 px-5 py-2.5 text-[13px] text-fg-3">
        <Cpu className="size-3.5" aria-hidden />
        <span>
          Extracted with <span className="font-mono text-fg-2">{model.label}</span>
          {model.own ? " (set under Advanced)." : ", the agent's main model."}
        </span>
        {showModelLink && (
          <Link to={agentEditPath(agentId, "advanced")} className="link-underline rounded-inline text-accent-text">
            Change model
          </Link>
        )}
        <span className="ml-auto font-mono tnum">
          {items.length}/{MAX_VARIABLES}
        </span>
      </div>
      {vars.isPending ? (
        <div className="flex flex-col gap-2 p-5">
          <Skeleton className="h-12 w-full" />
          <Skeleton className="h-12 w-full" />
        </div>
      ) : vars.isError ? (
        <p className="p-5 text-[13px] text-danger-text">{problemMessage(vars.error, "agent")}</p>
      ) : items.length === 0 ? (
        <EmptyState compact icon={<ClipboardText weight="duotone" />} title="No variables yet" className="py-8">
          Calls still get a summary and sentiment. Add a variable such as appointment_booked to track outcomes on every call.
        </EmptyState>
      ) : (
        <ol className="divide-y divide-line">
          <AnimatePresence initial={false}>
            {items.map((v, i) => {
              const Icon = TYPE_ICONS[v.type];
              return (
                <motion.li
                  key={v.id}
                  layout
                  initial={{ opacity: 0, y: -4 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, height: 0 }}
                  transition={{ duration: 0.2 }}
                  className="group flex items-start gap-3 px-5 py-3.5"
                >
                  <span className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-control bg-accent-soft text-accent-text [&_svg]:size-4">
                    <Icon aria-hidden />
                  </span>
                  <div className="flex min-w-0 flex-1 flex-col gap-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-mono text-[13px] font-medium text-fg">{v.name}</span>
                      <Badge>{TYPE_LABELS[v.type]}</Badge>
                    </div>
                    <p className="text-[13px] leading-relaxed text-fg-2">{v.description}</p>
                    {v.choices && v.choices.length > 0 && (
                      <ul className="mt-0.5 flex flex-wrap gap-1" aria-label={`Choices for ${v.name}`}>
                        {v.choices.map((c) => (
                          <li key={c} className="rounded-full bg-surface-3 px-2 py-0.5 text-[12px] text-fg-2">
                            {c}
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                  <div className="flex shrink-0 items-center gap-0.5 opacity-80 transition-opacity group-hover:opacity-100">
                    <IconButton label={`Move ${v.name} up`} disabled={i === 0} onClick={() => void move(i, -1)}>
                      <ArrowUp className="size-4" aria-hidden />
                    </IconButton>
                    <IconButton label={`Move ${v.name} down`} disabled={i === items.length - 1} onClick={() => void move(i, 1)}>
                      <ArrowDown className="size-4" aria-hidden />
                    </IconButton>
                    <IconButton label={`Edit ${v.name}`} onClick={() => setEditing({ open: true, variable: v })}>
                      <Pencil className="size-4" aria-hidden />
                    </IconButton>
                    <IconButton label={`Remove ${v.name}`} onClick={() => setRemoving(v)}>
                      <Trash2 className="size-4" aria-hidden />
                    </IconButton>
                  </div>
                </motion.li>
              );
            })}
          </AnimatePresence>
        </ol>
      )}
      <AddVariableDialog
        agentId={agentId}
        open={editing.open}
        existing={editing.variable}
        onOpenChange={(open) => setEditing((s) => ({ ...s, open }))}
      />
      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(o) => !o && setRemoving(null)}
        tone="danger"
        icon={<Trash2 aria-hidden />}
        title={`Remove ${removing?.name ?? "variable"}?`}
        description="Calls that end from now on stop extracting it. Calls that already captured it keep their values."
        confirmLabel="Remove variable"
        pending={busy}
        onConfirm={() => void remove()}
      />
    </section>
  );
}
