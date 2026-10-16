/**
 * Launch catalogs for the mock API, exactly as listed in specs/002-agent-builder/data-model.md
 * section 8 (languages, language models, speech recognition, voices, noise cancellation, ambient
 * sounds, control ranges). Prices are joined from the 001 pricing seed under the same ids, the way
 * the API joins its capability YAML with the pricing catalog (FR-039).
 */
import type { ControlRange, Language, LlmCatalog, NoiseCancellationOption, SttProvider, TtsProvider, VoiceCatalog } from "../../api/agents";
import { catalogV1 } from "../../lib/catalogSeed";
import { chimeDataUri } from "./audio";

function price(component: string, provider: string, model: string | null): string | null {
  const row = catalogV1.entries.find((e) => e.component === component && e.provider === provider && e.model === model);
  return row ? row.rate_per_min_usd : null;
}

// --- language models (8.2) ---------------------------------------------------

const LLM_MODELS = [
  { id: "gpt-5.1", label: "GPT-5.1", description: "Balanced quality and speed" },
  { id: "gpt-5.2", label: "GPT-5.2", description: "Strongest reasoning, highest cost" },
  { id: "gpt-5-mini", label: "GPT-5 Mini", description: "Fastest and cheapest" },
];

export const llmCatalog: LlmCatalog = {
  default: { provider: "azure_openai", model: "gpt-5.1" },
  providers: (
    [
      ["azure_openai", "Azure OpenAI"],
      ["openai", "OpenAI"],
    ] as const
  ).map(([id, label]) => ({
    id,
    label,
    models: LLM_MODELS.map((m) => ({
      id: m.id,
      label: m.label,
      family: "gpt-5",
      temperature: { fixed: 1, reason: "This model only supports temperature 1.0" },
      supports_tools: true,
      context_window: 400_000,
      input_tokens_bundle_per_min: 20_000,
      price_per_min_usd: price("llm", id, m.id),
      withdrawn: false,
    })),
  })),
};

// --- languages (8.1) ---------------------------------------------------------

const LANGS: [string, string][] = [
  ["multi", "Multilingual"],
  ["ar", "Arabic"],
  ["bn", "Bengali"],
  ["zh", "Chinese"],
  ["zh-CN", "Chinese (Simplified)"],
  ["zh-TW", "Chinese (Traditional)"],
  ["da", "Danish"],
  ["nl", "Dutch"],
  ["en", "English"],
  ["en-AU", "English (Australia)"],
  ["en-IN", "English (India)"],
  ["en-NZ", "English (New Zealand)"],
  ["en-GB", "English (UK)"],
  ["en-US", "English (US)"],
  ["fr", "French"],
  ["fr-CA", "French (Canada)"],
  ["de", "German"],
  ["gu", "Gujarati"],
  ["he", "Hebrew"],
  ["hi", "Hindi"],
  ["hi-Latn", "Hindi (Latin script)"],
  ["id", "Indonesian"],
  ["it", "Italian"],
  ["ja", "Japanese"],
  ["kn", "Kannada"],
  ["ko", "Korean"],
  ["ms", "Malay"],
  ["ml", "Malayalam"],
  ["mr", "Marathi"],
  ["no", "Norwegian"],
  ["or", "Odia"],
  ["pl", "Polish"],
  ["pt", "Portuguese"],
  ["pt-BR", "Portuguese (Brazil)"],
  ["pa", "Punjabi"],
  ["ru", "Russian"],
  ["es", "Spanish"],
  ["es-419", "Spanish (Latin America)"],
  ["sv", "Swedish"],
  ["taq", "Tamasheq"],
  ["ta", "Tamil"],
  ["te", "Telugu"],
  ["th", "Thai"],
  ["tr", "Turkish"],
  ["uk", "Ukrainian"],
  ["ur", "Urdu"],
];

const INDIC = ["bn", "gu", "hi", "hi-Latn", "kn", "ml", "mr", "or", "pa", "ta", "te"];
const ENGLISH = ["en", "en-AU", "en-IN", "en-NZ", "en-GB", "en-US"];
const ALL_CODES = LANGS.map(([c]) => c);
const NOVA2 = ALL_CODES.filter((c) => !INDIC.includes(c) || c === "hi");
const ASSEMBLY_MULTI = ["es", "es-419", "fr", "fr-CA", "de", "it", "pt", "pt-BR"];

export const DEFAULT_VOICE_BY_PROVIDER: Record<string, Record<string, string>> = {
  elevenlabs: Object.fromEntries(
    ALL_CODES.map((c) => [
      c,
      INDIC.includes(c) || c === "en-IN"
        ? "el_anika"
        : c.startsWith("es")
          ? "el_sofia"
          : c.startsWith("fr")
            ? "el_amelie"
            : c === "de"
              ? "el_jonas"
              : "el_jessica",
    ]),
  ),
  cartesia: Object.fromEntries(ALL_CODES.map((c) => [c, ENGLISH.includes(c) ? "ca_skylar" : c === "hi" || c === "en-IN" ? "ca_ishan" : "ca_lucia"])),
  fishaudio: Object.fromEntries(ALL_CODES.map((c) => [c, ENGLISH.includes(c) ? "fa_aria" : "fa_mira"])),
};

const languages: Language[] = LANGS.map(([code, label]) => ({
  code,
  label,
  stt_default: { provider: INDIC.includes(code) ? "sarvam" : "deepgram", model: null },
  tts_default: { provider: "elevenlabs", model: "eleven_flash_v2_5", voice_id: DEFAULT_VOICE_BY_PROVIDER.elevenlabs![code]! },
}));

// --- speech recognition (8.3) ------------------------------------------------

const stt: SttProvider[] = [
  {
    provider: "deepgram",
    label: "Deepgram",
    supports_auto: true,
    default_model: null,
    auto_rule: { default: "nova-2", by_language: { en: "nova-3" } },
    models: [
      {
        id: "nova-3",
        label: "Nova-3",
        description: "Most accurate for English",
        languages: ENGLISH,
        builtin_turn_detection: false,
        price_per_min_usd: price("stt", "deepgram", "nova-3"),
        withdrawn: false,
      },
      {
        id: "nova-2",
        label: "Nova-2",
        description: "Broad language coverage (36 languages)",
        languages: NOVA2,
        builtin_turn_detection: false,
        price_per_min_usd: price("stt", "deepgram", "nova-2"),
        withdrawn: false,
      },
      {
        id: "flux-general-en",
        label: "Flux",
        description: "Conversational English, lowest latency",
        languages: ENGLISH,
        builtin_turn_detection: true,
        price_per_min_usd: price("stt", "deepgram", "flux-general-en"),
        withdrawn: false,
      },
    ],
  },
  {
    provider: "assemblyai",
    label: "AssemblyAI",
    supports_auto: true,
    default_model: null,
    auto_rule: { default: "universal-streaming-multilingual", by_language: { en: "universal-streaming" } },
    models: [
      {
        id: "universal-streaming",
        label: "Universal Streaming",
        description: "English-focused",
        languages: ENGLISH,
        builtin_turn_detection: true,
        price_per_min_usd: price("stt", "assemblyai", "universal-streaming"),
        withdrawn: false,
      },
      {
        id: "universal-streaming-multilingual",
        label: "Universal Streaming Multilingual",
        description: "Spanish, French, German, Italian, Portuguese",
        languages: ASSEMBLY_MULTI,
        builtin_turn_detection: true,
        price_per_min_usd: price("stt", "assemblyai", "universal-streaming-multilingual"),
        withdrawn: false,
      },
    ],
  },
  {
    provider: "sarvam",
    label: "Sarvam AI",
    supports_auto: true,
    default_model: null,
    auto_rule: { default: "saarika:v2.5", by_language: {} },
    models: [
      {
        id: "saarika:v2.5",
        label: "Saarika v2.5",
        description: "Transcribes in the spoken language",
        languages: [...INDIC, "en-IN"],
        builtin_turn_detection: false,
        price_per_min_usd: price("stt", "sarvam", "saarika:v2.5"),
        withdrawn: false,
      },
      {
        id: "saaras:v3",
        label: "Saaras v3",
        description: "Newest Sarvam model",
        languages: [...INDIC, "en-IN"],
        builtin_turn_detection: false,
        price_per_min_usd: price("stt", "sarvam", "saaras:v3"),
        withdrawn: false,
      },
    ],
  },
];

/** Price of Auto for a provider (the catalog row with a null model). */
export const sttAutoPrice = (provider: string) => price("stt", provider, null);

// --- voices (8.4) ------------------------------------------------------------

const tts: TtsProvider[] = [
  {
    provider: "elevenlabs",
    label: "ElevenLabs",
    default_model: "eleven_flash_v2_5",
    default_voice_by_language: DEFAULT_VOICE_BY_PROVIDER.elevenlabs,
    voice_listing: { source: "live", server_search: true, gender_filter: true, language_filter: true, previews: true },
    capabilities: { speed: true, expressiveness: true, volume: true },
    models: [
      ["eleven_flash_v2_5", "Flash v2.5", "Low latency, 32 languages"],
      ["eleven_flash_v2", "Flash v2", "Low latency, English"],
      ["eleven_turbo_v2_5", "Turbo v2.5", "Fast, 32 languages"],
      ["eleven_turbo_v2", "Turbo v2", "Fast, English"],
      ["eleven_multilingual_v2", "Multilingual v2", "Highest quality, 29 languages"],
    ].map(([id, label, description]) => ({
      id: id!,
      label: label!,
      description,
      chars_bundle_per_min: 750,
      price_per_min_usd: price("tts", "elevenlabs", id!),
      withdrawn: false,
    })),
  },
  {
    provider: "cartesia",
    label: "Cartesia",
    default_model: "sonic-2",
    default_voice_by_language: DEFAULT_VOICE_BY_PROVIDER.cartesia,
    voice_listing: { source: "live", server_search: false, gender_filter: true, language_filter: true, previews: false },
    capabilities: { speed: true, expressiveness: true, volume: true },
    models: [
      ["sonic-2", "Sonic 2", "Default, steady delivery"],
      ["sonic-2-2025-03-07", "Sonic 2 (2025-03-07)", "Speed and emotion controls"],
      ["sonic-3", "Sonic 3", "Newest Cartesia model"],
      ["sonic-turbo", "Sonic Turbo", "Fastest first audio"],
    ].map(([id, label, description]) => ({
      id: id!,
      label: label!,
      description,
      chars_bundle_per_min: 750,
      price_per_min_usd: price("tts", "cartesia", id!),
      withdrawn: false,
    })),
  },
  {
    provider: "fishaudio",
    label: "Fish Audio",
    default_model: "s2.1-pro",
    default_voice_by_language: DEFAULT_VOICE_BY_PROVIDER.fishaudio,
    voice_listing: { source: "curated", server_search: false, gender_filter: false, language_filter: true, previews: true },
    capabilities: { speed: true, expressiveness: true, volume: true },
    models: [
      ["s2.1-pro", "S2.1 Pro", "Newest Fish Audio model"],
      ["s2-pro", "S2 Pro", "Multi-speaker conversations"],
      ["s1", "S1", "Standard quality"],
    ].map(([id, label, description]) => ({
      id: id!,
      label: label!,
      description,
      chars_bundle_per_min: 750,
      price_per_min_usd: price("tts", "fishaudio", id!),
      withdrawn: false,
    })),
  },
];

// --- noise cancellation (8.5) -----------------------------------------------

const noise_cancellation: NoiseCancellationOption[] = [
  {
    provider: "sanas",
    model: "vi",
    label: "Voice isolation",
    description: "Removes background noise and other voices; best for noisy callers",
    default: true,
    price_per_min_usd: price("nc", "sanas", "vi"),
  },
  {
    provider: "sanas",
    model: "st",
    label: "Standard noise removal",
    description: "Removes noise and keeps every voice; best when several people speak",
    default: false,
    price_per_min_usd: price("nc", "sanas", "st"),
  },
  {
    provider: "ai_coustics",
    model: "standard",
    label: "Lightweight noise removal",
    description: "Light processing with the lowest overhead",
    default: false,
    price_per_min_usd: price("nc", "ai_coustics", "standard"),
  },
];

// --- control ranges (8.6) ----------------------------------------------------

export const controls: ControlRange[] = [
  { path: "/tts/speed", label: "Voice speed", min: 0.5, max: 2, step: 0.1, unit: "x", display: "multiplier" },
  { path: "/tts/expressiveness", label: "Expressiveness", min: 0, max: 2, step: 0.1, unit: null, display: "decimal" },
  { path: "/tts/volume", label: "Volume", min: 0, max: 2, step: 0.05, unit: null, display: "percent_of_normal" },
  { path: "/call_behavior/end_on_silence_s", label: "End call after silence", min: 10, max: 300, step: 10, unit: "s", display: "duration" },
  { path: "/call_behavior/max_duration_s", label: "Maximum call duration", min: 30, max: 3600, step: 30, unit: "s", display: "duration" },
  { path: "/call_behavior/ring_duration_ms", label: "Ring time", min: 0, max: 30000, step: 500, unit: "ms", display: "duration" },
  { path: "/call_behavior/interruption_sensitivity", label: "Interruption sensitivity", min: 0, max: 1, step: 0.05, unit: null, display: "decimal" },
  { path: "/call_behavior/responsiveness", label: "Responsiveness", min: 0, max: 1, step: 0.05, unit: null, display: "decimal" },
  { path: "/advanced/webhook_timeout_ms", label: "Webhook timeout", min: 1000, max: 30000, step: 500, unit: "ms", display: "duration" },
  { path: "/advanced/dtmf/timeout_ms", label: "Keypad pause", min: 1000, max: 10000, step: 500, unit: "ms", display: "duration" },
  { path: "/advanced/background_audio/volume", label: "Background volume", min: 0, max: 3, step: 0.05, unit: null, display: "percent_of_normal" },
];

const AMBIENT: [string, string][] = [
  ["office_ambience", "Office ambience"],
  ["city_ambience", "City ambience"],
  ["forest_ambience", "Forest ambience"],
  ["crowded_room", "Crowded room"],
  ["hold_music", "Hold music"],
  ["keyboard_typing", "Keyboard typing"],
  ["keyboard_typing2", "Keyboard typing (soft)"],
];

export const voiceCatalog: VoiceCatalog = {
  controls,
  languages,
  stt,
  tts,
  noise_cancellation,
  ambient_sounds: AMBIENT.map(([id, label], i) => ({ id, label, preview_url: chimeDataUri(3 + i) })),
};
