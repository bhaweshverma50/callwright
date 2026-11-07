/**
 * Display names for providers (catalog ids are snake_case strings, never enums). The pricing
 * catalog, the one the public pages can read, labels models but not providers, so the names live
 * here; signed-in pickers use the labels the voice and model catalogs serve.
 */
export const PROVIDER_LABELS: Record<string, string> = {
  deepgram: "Deepgram",
  assemblyai: "AssemblyAI",
  sarvam: "Sarvam",
  azure_openai: "Azure OpenAI",
  openai: "OpenAI",
  anthropic: "Anthropic",
  elevenlabs: "ElevenLabs",
  cartesia: "Cartesia",
  fishaudio: "Fish Audio",
  sanas: "Sanas",
  ai_coustics: "ai-coustics",
  callwright: "Callwright",
};

export const providerLabel = (id: string) => PROVIDER_LABELS[id] ?? id;
