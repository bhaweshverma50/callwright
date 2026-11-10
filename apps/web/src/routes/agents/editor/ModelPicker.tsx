import { BrainCircuit, Building2 } from "lucide-react";
import { FieldRow, Select } from "../../../components";
import { isFixed, llmModel, perMin, providerLabel, type Catalogs } from "./catalogs";
import { FieldError, FieldWarning } from "./fields";
import type { AgentDraft } from "./useAgentDraft";
import { fieldId, fieldLabel } from "../config/fields";

/**
 * Model provider and language model (FR-005, FR-031). Each model option shows its price per
 * minute. Switching model applies a fixed temperature, or clamps the current one into the new
 * model's range and reports it through `onClamp`.
 */
export function ModelPicker({ draft, catalogs, onClamp }: { draft: AgentDraft; catalogs: Catalogs; onClamp: (msg: string | null) => void }) {
  const { llm } = draft.config;
  const provider = catalogs.llm.providers.find((p) => p.id === llm.provider);
  const setModel = (providerId: string, modelId: string) => {
    const m = llmModel(catalogs.llm, providerId, modelId);
    draft.update((c) => {
      c.llm.provider = providerId;
      c.llm.model = modelId;
      if (!m) return;
      const r = m.temperature;
      if (isFixed(r)) c.llm.temperature = r.fixed;
      else if (c.llm.temperature < r.min || c.llm.temperature > r.max) {
        const clamped = Math.min(r.max, Math.max(r.min, c.llm.temperature));
        onClamp(`Temperature changed from ${c.llm.temperature.toFixed(2)} to ${clamped.toFixed(2)} to fit ${m.label}'s range.`);
        c.llm.temperature = clamped;
      }
    });
    draft.touch("/llm/model");
  };
  return (
    <>
      <FieldRow
        icon={<Building2 />}
        label={fieldLabel("/llm/provider")}
        htmlFor={fieldId("/llm/provider")}
        description="The same models are offered by both providers."
      >
        <Select
          id={fieldId("/llm/provider")}
          className="w-full"
          value={llm.provider}
          onValueChange={(p) => {
            const next = catalogs.llm.providers.find((x) => x.id === p);
            const keep = next?.models.some((m) => m.id === llm.model && !m.withdrawn);
            setModel(p, keep ? llm.model : (next?.models.find((m) => !m.withdrawn)?.id ?? llm.model));
          }}
          options={catalogs.llm.providers.map((p) => ({ value: p.id, label: providerLabel(p) }))}
        />
        <FieldWarning draft={draft} pointer="/llm/provider" />
      </FieldRow>
      <FieldRow
        icon={<BrainCircuit />}
        label={fieldLabel("/llm/model")}
        htmlFor={fieldId("/llm/model")}
        description="Decides what the agent says. Prices are per minute of call."
        hint="Each minute includes 20,000 input and 200 output tokens. A call that uses more bills the model for more minutes than it lasted."
      >
        <Select
          id={fieldId("/llm/model")}
          className="w-full"
          value={llm.model}
          invalid={Boolean(draft.errorFor("/llm/model"))}
          onValueChange={(m) => setModel(llm.provider, m)}
          options={(provider?.models ?? [])
            .filter((m) => !m.withdrawn || m.id === llm.model)
            .map((m) => ({ value: m.id, label: m.withdrawn ? `${m.label} (withdrawn)` : m.label, meta: perMin(m.price_per_min_usd) }))}
        />
        <FieldError message={draft.errorFor("/llm/model")} />
      </FieldRow>
    </>
  );
}
