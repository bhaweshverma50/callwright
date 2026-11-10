import { AudioLines, Ban, Users, Feather } from "lucide-react";
import { ChoiceGroup } from "../../../components";
import { perMin, type Catalogs } from "./catalogs";
import { FieldError, FieldWarning, StackRow } from "./fields";
import type { AgentDraft } from "./useAgentDraft";
import { fieldId, fieldLabel } from "../config/fields";

const OFF = "off";
const ICONS: Record<string, typeof AudioLines> = { "sanas/vi": AudioLines, "sanas/st": Users, "ai_coustics/standard": Feather };

/**
 * Noise cancellation (T041, FR-005). Every option shows its description and price; "Off" removes
 * the line from the cost card. The control always shows the saved choice, never a blank.
 */
export function NoiseCancellationSelect({ draft, catalogs }: { draft: AgentDraft; catalogs: Catalogs }) {
  const nc = draft.config.noise_cancellation;
  const value = nc ? `${nc.provider}/${nc.model}` : OFF;
  return (
    <StackRow
      icon={<AudioLines />}
      label={fieldLabel("/noise_cancellation")}
      description="Cleans up the caller's audio before speech recognition hears it."
    >
      <ChoiceGroup
        id={fieldId("/noise_cancellation")}
        aria-label={fieldLabel("/noise_cancellation")}
        size="sm"
        columns={2}
        value={value}
        onValueChange={(v) => {
          draft.update((c) => {
            if (v === OFF) c.noise_cancellation = null;
            else {
              const [provider = "", model = ""] = v.split("/");
              c.noise_cancellation = { provider, model };
            }
          });
          draft.touch("/noise_cancellation");
        }}
        options={[
          ...catalogs.voice.noise_cancellation.map((o) => {
            const Icon = ICONS[`${o.provider}/${o.model}`] ?? AudioLines;
            return {
              value: `${o.provider}/${o.model}`,
              title: o.available === false ? `${o.label} (not set up on this platform)` : o.label,
              description: o.description ?? undefined,
              meta: perMin(o.price_per_min_usd),
              icon: <Icon aria-hidden />,
            };
          }),
          { value: OFF, title: "Off", description: "The caller's audio goes to speech recognition untouched.", icon: <Ban aria-hidden /> },
        ]}
      />
      <FieldWarning draft={draft} pointer="/noise_cancellation/provider" />
      <FieldError message={draft.errorFor("/noise_cancellation")} />
    </StackRow>
  );
}
