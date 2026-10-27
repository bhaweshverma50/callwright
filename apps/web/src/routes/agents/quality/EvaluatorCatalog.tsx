import { ShieldCheck } from "@phosphor-icons/react";
import { useQueryClient } from "@tanstack/react-query";
import { Coins, Plus, Star, Trash2 } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { problemMessage } from "../../../api/problems";
import { deleteCustomEvaluator, qualityKeys, useEvalSettings, useEvaluators, useJudgeModels, type Evaluator } from "../../../api/quality";
import { Button, ConfirmDialog, Skeleton, toast } from "../../../components";
import { CustomEvaluatorDialog } from "../../evaluators/CustomEvaluatorDialog";
import { TabHeader } from "../tools/TabHeader";
import { EvaluatorCard, HEADLINE_LIMIT } from "./EvaluatorCard";

function Stat({ icon, value, label }: { icon: ReactNode; value: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-[12.5px] text-fg-3 [&_svg]:size-3.5">
      {icon}
      <span className="font-mono text-fg-2 tnum">{value}</span>
      {label}
    </span>
  );
}

/**
 * The agent's checks (US2, T042): every built-in that applies to the agent type plus the
 * workspace's custom checks, alphabetical by display name, each with its on/off switch, settings
 * and headline star (up to 4 for the dashboard).
 */
export function EvaluatorCatalog({ agentId }: { agentId: string }) {
  const qc = useQueryClient();
  const settings = useEvalSettings(agentId);
  const models = useJudgeModels();
  const customs = useEvaluators({ kind: "custom" });
  const [dialog, setDialog] = useState<{ open: boolean; existing: Evaluator | null }>({ open: false, existing: null });
  const [removing, setRemoving] = useState<Evaluator | null>(null);
  const [busy, setBusy] = useState(false);

  const items = useMemo(() => [...(settings.data ?? [])].sort((a, b) => a.display_name.localeCompare(b.display_name)), [settings.data]);
  const customById = useMemo(() => new Map((customs.data ?? []).map((c) => [c.id, c])), [customs.data]);
  const on = items.filter((s) => s.enabled).length;
  const headline = items.filter((s) => s.is_headline).length;
  const judgesOn = items.filter((s) => s.enabled && s.cost_class === "llm_judge").length;

  const remove = async () => {
    if (!removing) return;
    setBusy(true);
    try {
      await deleteCustomEvaluator(removing.id);
      toast({ title: `Deleted ${removing.display_name}`, description: "Past results keep showing under its last version." });
      setRemoving(null);
      await qc.invalidateQueries({ queryKey: qualityKeys.all });
    } catch (e) {
      toast({ tone: "error", title: "Could not delete the check", description: problemMessage(e, "check") });
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="rounded-panel border border-line bg-surface shadow-1">
      <TabHeader
        icon={<ShieldCheck weight="duotone" aria-hidden />}
        title="Quality checks"
        description="Checks run after every call and leave a verdict with a reason. Settings apply to calls that end from now on."
        actions={
          <Button size="sm" icon={<Plus aria-hidden />} onClick={() => setDialog({ open: true, existing: null })}>
            Add custom check
          </Button>
        }
      />
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5 border-b border-line bg-surface-2/40 px-5 py-2.5">
        <Stat icon={<ShieldCheck weight="duotone" />} value={`${on}/${items.length}`} label="on" />
        <Stat icon={<Star />} value={`${headline}/${HEADLINE_LIMIT}`} label="headline on the dashboard" />
        <Stat icon={<Coins />} value={String(judgesOn)} label={judgesOn === 1 ? "model judge on" : "model judges on"} />
      </div>
      <div className="p-4">
        {settings.isPending ? (
          <div className="flex flex-col gap-2">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-[74px] w-full rounded-control" />
            ))}
          </div>
        ) : settings.isError ? (
          <p className="text-[13px] text-danger-text">{problemMessage(settings.error, "agent")}</p>
        ) : (
          <ul className="flex flex-col gap-2" aria-label="Checks">
            {items.map((s) => {
              const custom = customById.get(s.evaluator_id);
              return (
                <EvaluatorCard
                  key={s.evaluator_id}
                  agentId={agentId}
                  setting={s}
                  models={models.data}
                  headlineCount={headline}
                  evaluatorType={custom?.evaluator_type}
                  onEditCustom={custom ? () => setDialog({ open: true, existing: custom }) : undefined}
                  onDeleteCustom={custom ? () => setRemoving(custom) : undefined}
                />
              );
            })}
          </ul>
        )}
      </div>
      <CustomEvaluatorDialog open={dialog.open} existing={dialog.existing} onOpenChange={(open) => setDialog((d) => ({ ...d, open }))} />
      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(o) => !o && setRemoving(null)}
        tone="danger"
        icon={<Trash2 aria-hidden />}
        title={`Delete ${removing?.display_name ?? "check"}?`}
        description="It disappears from every agent's catalog and stops running. Results it already produced stay, under its last version."
        confirmLabel="Delete check"
        pending={busy}
        onConfirm={() => void remove()}
      />
    </section>
  );
}
