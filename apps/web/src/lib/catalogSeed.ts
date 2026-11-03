/**
 * Pricing catalog version 1, exactly as seeded by 001 data-model.md (32 rows). Typed against the
 * contract so drift in the schema breaks the build.
 */
import type { Catalog, CatalogEntry } from "../api/types";

const llmBundles: CatalogEntry["bundles"] = [
  { unit: "llm_input_tokens", per_min: 20000 },
  { unit: "llm_output_tokens", per_min: 200 },
];
const ttsBundles: CatalogEntry["bundles"] = [{ unit: "tts_chars", per_min: 750 }];

type Row = [CatalogEntry["component"], string, string | null, string, string];
const rows: Row[] = [
  ["stt", "deepgram", null, "Deepgram, Auto", "0.0085"],
  ["stt", "deepgram", "nova-3", "Nova-3", "0.0085"],
  ["stt", "deepgram", "nova-2", "Nova-2", "0.0058"],
  ["stt", "deepgram", "flux-general-en", "Flux", "0.0085"],
  ["stt", "assemblyai", null, "AssemblyAI, Auto", "0.0030"],
  ["stt", "assemblyai", "universal-streaming", "Universal Streaming", "0.0030"],
  ["stt", "assemblyai", "universal-streaming-multilingual", "Universal Streaming Multilingual", "0.0030"],
  ["stt", "sarvam", null, "Sarvam, Auto", "0.0060"],
  ["stt", "sarvam", "saarika:v2.5", "Saarika v2.5", "0.0060"],
  ["stt", "sarvam", "saaras:v3", "Saaras v3", "0.0060"],
  ["llm", "azure_openai", "gpt-5-mini", "GPT-5 Mini", "0.0015"],
  ["llm", "azure_openai", "gpt-5.1", "GPT-5.1", "0.0165"],
  ["llm", "azure_openai", "gpt-5.2", "GPT-5.2", "0.0315"],
  ["llm", "openai", "gpt-5-mini", "GPT-5 Mini", "0.0015"],
  ["llm", "openai", "gpt-5.1", "GPT-5.1", "0.0165"],
  ["llm", "openai", "gpt-5.2", "GPT-5.2", "0.0315"],
  ["tts", "elevenlabs", "eleven_flash_v2_5", "Flash v2.5", "0.0450"],
  ["tts", "elevenlabs", "eleven_flash_v2", "Flash v2", "0.0450"],
  ["tts", "elevenlabs", "eleven_turbo_v2_5", "Turbo v2.5", "0.0450"],
  ["tts", "elevenlabs", "eleven_turbo_v2", "Turbo v2", "0.0450"],
  ["tts", "elevenlabs", "eleven_multilingual_v2", "Multilingual v2", "0.0900"],
  ["tts", "cartesia", "sonic-2", "Sonic 2", "0.0275"],
  ["tts", "cartesia", "sonic-2-2025-03-07", "Sonic 2 (2025-03-07)", "0.0275"],
  ["tts", "cartesia", "sonic-3", "Sonic 3", "0.0275"],
  ["tts", "cartesia", "sonic-turbo", "Sonic Turbo", "0.0275"],
  ["tts", "fishaudio", "s2.1-pro", "S2.1 Pro", "0.0150"],
  ["tts", "fishaudio", "s2-pro", "S2 Pro", "0.0150"],
  ["tts", "fishaudio", "s1", "S1", "0.0150"],
  ["nc", "sanas", "vi", "Voice isolation", "0.0000"],
  ["nc", "sanas", "st", "Standard noise removal", "0.0000"],
  ["nc", "ai_coustics", "standard", "Lightweight noise removal", "0.0000"],
  ["platform", "callwright", null, "Callwright platform fee", "0.0500"],
];

export const catalogV1: Catalog = {
  version: 1,
  effective_from: "2026-10-16T00:00:00Z",
  entries: rows.map(([component, provider, model, label, rate]) => ({
    component,
    provider,
    model,
    label,
    rate_per_min_usd: rate,
    bundles: component === "llm" ? llmBundles : component === "tts" ? ttsBundles : [],
  })),
};

/**
 * Rows a later migration added to the catalog in effect (services/api s003_0004, 003 T069). The
 * mock API serves `catalogCurrent`; the public pages keep describing the launch catalog.
 */
const addedRows: Row[] = [
  ["llm", "anthropic", "claude-haiku-5-5", "Claude Haiku 5.5", "0.0021"],
  ["llm", "anthropic", "claude-sonnet-5-5", "Claude Sonnet 5.5", "0.0420"],
];

export const catalogCurrent: Catalog = {
  ...catalogV1,
  entries: [
    ...catalogV1.entries,
    ...addedRows.map(([component, provider, model, label, rate]) => ({
      component,
      provider,
      model,
      label,
      rate_per_min_usd: rate,
      bundles: llmBundles,
    })),
  ],
};

/** Display name for a catalog row ("Nova-3", "GPT-5 Mini"); falls back to the raw model id. */
export function modelLabel(component: string, provider: string, model: string | null | undefined): string | null {
  const row = catalogCurrent.entries.find((e) => e.component === component && e.provider === provider && e.model === (model ?? null));
  return row?.label ?? model ?? null;
}
