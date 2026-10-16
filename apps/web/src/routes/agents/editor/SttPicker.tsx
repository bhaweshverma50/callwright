import { Captions, Cpu, Wand2 } from "lucide-react";
import { ChoiceGroup, FieldRow, Select } from "../../../components";
import { fieldId } from "../versions/versionLabels";
import { languageLabel, perMin, type Catalogs } from "./catalogs";
import { FieldError, StackRow } from "./fields";
import type { AgentDraft } from "./useAgentDraft";
import { useCatalog } from "../../../api/queries";

const AUTO = "__auto__";

/**
 * Speech recognition provider and model (FR-011, T041). Auto lets the platform pick the best model
 * for the language; models that do not cover the agent's language are shown but disabled with the
 * reason, and a provider with a single model selects it and locks the choice.
 */
export function SttPicker({ draft, catalogs }: { draft: AgentDraft; catalogs: Catalogs }) {
  const { stt, language } = draft.config;
  const pricing = useCatalog();
  // Auto has its own pricing row with no model (001 catalog); the speech catalog prices models only.
  const autoPrice = (p: string) =>
    pricing.data?.entries.find((e) => e.component === "stt" && e.provider === p && e.model === null)?.rate_per_min_usd ?? null;
  const provider = catalogs.voice.stt.find((p) => p.provider === stt.provider);
  const lang = languageLabel(catalogs.voice, language);
  const models = provider?.models.filter((m) => !m.withdrawn || m.id === stt.model) ?? [];
  const single = provider && !provider.supports_auto && models.length === 1;
  const autoRule = provider?.auto_rule as { default?: string; by_language?: Record<string, string> } | null | undefined;
  const autoPick = autoRule ? (autoRule.by_language?.[language] ?? autoRule.by_language?.[language.split("-")[0]!] ?? autoRule.default) : undefined;
  const autoPickLabel = models.find((m) => m.id === autoPick)?.label;

  const options = [
    ...(provider?.supports_auto
      ? [
          {
            value: AUTO,
            title: "Auto",
            icon: <Wand2 aria-hidden />,
            meta: pricing.data ? perMin(autoPrice(provider.provider)) : undefined,
            description: autoPickLabel ? `Uses ${autoPickLabel} for ${lang}, and newer models as they arrive.` : `Picks the best model for ${lang}.`,
          },
        ]
      : []),
    ...models.map((m) => {
      const covers = m.languages.includes(language);
      return {
        value: m.id,
        title: m.label,
        icon: <Cpu aria-hidden />,
        meta: perMin(m.price_per_min_usd),
        description: covers ? (m.description ?? undefined) : `Does not recognise ${lang}.`,
        disabled: !covers || Boolean(single),
      };
    }),
  ];

  return (
    <>
      <FieldRow
        icon={<Captions />}
        label="Speech recognition provider"
        htmlFor={fieldId("/stt/provider")}
        description="Turns what the caller says into text."
      >
        <Select
          id={fieldId("/stt/provider")}
          className="w-full"
          value={stt.provider}
          invalid={Boolean(draft.errorFor("/stt/provider"))}
          onValueChange={(p) => {
            const next = catalogs.voice.stt.find((x) => x.provider === p);
            const only = next && !next.supports_auto && next.models.length === 1 ? next.models[0]!.id : null;
            draft.update((c) => void (c.stt = { provider: p, model: next?.supports_auto ? null : (only ?? next?.default_model ?? null) }));
            draft.touch("/stt/provider");
          }}
          options={catalogs.voice.stt.map((p) => ({ value: p.provider, label: p.label }))}
        />
        <FieldError message={draft.errorFor("/stt/provider")} />
      </FieldRow>
      <StackRow
        icon={<Cpu />}
        label="Speech recognition model"
        description={single ? "This provider has one model for the language, so it is selected for you." : "Auto is right for most agents."}
        hint="Auto resolves when each call starts, so a better model for the language is used as soon as the platform adds one. Calls are billed for the model that ran."
      >
        <ChoiceGroup
          id={fieldId("/stt/model")}
          aria-label="Speech recognition model"
          size="sm"
          columns={2}
          value={stt.model ?? AUTO}
          onValueChange={(v) => {
            draft.update((c) => void (c.stt.model = v === AUTO ? null : v));
            draft.touch("/stt/model");
          }}
          options={options}
        />
        <FieldError message={draft.errorFor("/stt/model")} />
      </StackRow>
    </>
  );
}
