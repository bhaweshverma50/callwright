/** Display names for providers (catalog ids are snake_case strings, never enums). */
export const PROVIDER_LABELS: Record<string, string> = {
  deepgram: "Deepgram",
  assemblyai: "AssemblyAI",
  sarvam: "Sarvam",
  azure_openai: "Azure OpenAI",
  openai: "OpenAI",
  elevenlabs: "ElevenLabs",
  cartesia: "Cartesia",
  fishaudio: "Fish Audio",
  sanas: "Sanas",
  ai_coustics: "ai-coustics",
  callwright: "Callwright",
};

export const providerLabel = (id: string) => PROVIDER_LABELS[id] ?? id;
