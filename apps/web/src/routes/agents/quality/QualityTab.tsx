import { ShieldCheck } from "@phosphor-icons/react";
import { EmptyState } from "../../../components";
import type { EditorPanelProps } from "../editor/panels";
import { AnalysisVariablesEditor } from "./AnalysisVariablesEditor";
import { EvaluatorCatalog } from "./EvaluatorCatalog";

/**
 * The agent's Quality tab (spec 007, mounted through 002's editor panel slots in both the
 * single-prompt editor and the flow builder). Variables and checks are per agent, not part of the
 * draft, so they save on their own and never need a publish.
 */
export function QualityTab({ agentId, agentType, config }: EditorPanelProps) {
  if (!agentId) {
    return (
      <EmptyState icon={<ShieldCheck weight="duotone" />} title="Save the agent first">
        Post-call analysis and quality checks are set per agent. Save this agent once to set them up.
      </EmptyState>
    );
  }
  return (
    <div className="flex flex-col gap-5">
      <AnalysisVariablesEditor agentId={agentId} config={config} showModelLink={agentType === "single_prompt"} />
      <EvaluatorCatalog agentId={agentId} />
    </div>
  );
}
