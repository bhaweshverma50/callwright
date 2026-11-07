/**
 * The workspace's default stack and money-to-talk-time conversion (docs/DESIGN.md principle 2).
 * Prices and names come from the served catalog and quote (/pricing/catalog, /pricing/quote), so
 * the marketing pages, billing and the editor all show what the API charges.
 */
import { toMicros } from "../lib/money";
import { useCatalog, useQuote } from "./queries";
import type { CostBreakdown, QuoteRequest } from "./types";

/** Every workspace starts on this stack: Deepgram Nova-3, GPT-5 Mini on Azure OpenAI, ElevenLabs Multilingual v2. */
export const DEFAULT_STACK: QuoteRequest["components"] = {
  stt: { provider: "deepgram", model: "nova-3" },
  llm: { provider: "azure_openai", model: "gpt-5-mini" },
  tts: { provider: "elevenlabs", model: "eleven_multilingual_v2" },
  nc: null,
};

/** Whole minutes of calls a balance pays for at a per-minute price (never negative). */
export function talkMinutes(balanceMicros: bigint, perMinuteMicros: bigint): number {
  if (perMinuteMicros <= 0n || balanceMicros <= 0n) return 0;
  return Number(balanceMicros / perMinuteMicros);
}

/** The default stack's per-minute price in micro-dollars; undefined until the quote loads (or when not `enabled`). */
export function useStackRate(enabled = true): bigint | undefined {
  const quote = useQuote(enabled ? { components: DEFAULT_STACK } : null);
  return quote.data ? (toMicros(quote.data.per_minute_total_usd) ?? undefined) : undefined;
}

/** Catalog entries in effect now; empty until the catalog loads. */
export function useCatalogEntries() {
  return useCatalog().data?.entries ?? [];
}

/**
 * The spec 001 reference call (US3): 271 s, 102,348 input tokens, 745 output tokens, 2,555 TTS
 * characters on Deepgram Nova-3, GPT-5 Mini and ElevenLabs Flash v2.5, priced by the API.
 */
export const REFERENCE_CALL = {
  components: {
    stt: { provider: "deepgram", model: "nova-3" },
    llm: { provider: "azure_openai", model: "gpt-5-mini" },
    tts: { provider: "elevenlabs", model: "eleven_flash_v2_5" },
    nc: null,
  },
  usage: { duration_ms: 271_000, llm_input_tokens: 102_348, llm_output_tokens: 745, tts_chars: 2_555 },
} satisfies QuoteRequest;

/** The reference call's receipt; undefined until the quote loads. */
export function useReferenceBreakdown(): CostBreakdown | undefined {
  return useQuote(REFERENCE_CALL).data?.call;
}
