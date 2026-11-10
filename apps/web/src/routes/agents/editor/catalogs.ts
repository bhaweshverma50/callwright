/** Catalog lookups the editor sections share (labels, prices, defaults). */
import type { LlmCatalog, LlmModel, TemperatureRule, VoiceCatalog } from "../../../api/agents";
import { formatUsd } from "../../../lib/money";
import { scanPlaceholders } from "../../../lib/agentVariables";
import type { AgentConfig } from "../../../api/agents";

export interface Catalogs {
  llm: LlmCatalog;
  voice: VoiceCatalog;
}

/** "$0.0165/min", or "Price unavailable" (never $0.0000 for a missing price, US4.5). */
export function perMin(price: string | null | undefined): string {
  return price == null ? "Price unavailable" : `${formatUsd(price, { places: 4 })}/min`;
}

/** A provider's name in a picker; "Not set up on this platform" when the voice worker has no key for it. */
export function providerLabel(p: { label: string; available?: boolean }): string {
  return p.available === false ? `${p.label} (not set up on this platform)` : p.label;
}

export function llmModel(cat: LlmCatalog, provider: string, model: string): LlmModel | undefined {
  return cat.providers.find((p) => p.id === provider)?.models.find((m) => m.id === model);
}

export function llmLabel(cat: LlmCatalog | undefined, ref: string): string {
  const [provider = "", model = ""] = ref.includes("/") ? ref.split("/") : ["", ref];
  const m =
    cat?.providers.find((p) => p.id === provider)?.models.find((x) => x.id === model) ??
    cat?.providers.flatMap((p) => p.models).find((x) => x.id === model);
  return m?.label ?? model;
}

export const isFixed = (r: TemperatureRule): r is { fixed: number; reason: string } => "fixed" in r;

export function languageLabel(cat: VoiceCatalog | undefined, code: string): string {
  return cat?.languages.find((l) => l.code === code)?.label ?? code;
}

/** Adds every `{{name}}` used in the prompt or greeting to the variables list (US1.4). */
export function syncVariables(c: AgentConfig) {
  const scan = scanPlaceholders(c.prompt, c.begin_message);
  for (const name of scan.names) {
    if (!c.dynamic_variables.some((v) => v.name === name) && c.dynamic_variables.length < 50) c.dynamic_variables.push({ name, default: null });
  }
}
