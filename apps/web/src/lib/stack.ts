/**
 * The workspace's default stack and money-to-talk-time conversion (docs/DESIGN.md principle 2).
 * Until agents ship (spec 002) every workspace runs the reference stack: Deepgram Nova-3, GPT-5
 * Mini on Azure OpenAI, ElevenLabs Flash v2.5, no noise cancellation.
 */
import type { QuoteRequest } from "../api/types";
import { catalogV1 } from "./catalogSeed";
import { toMicros } from "./money";
import { priceQuote } from "./pricing";

export const DEFAULT_STACK: QuoteRequest["components"] = {
  stt: { provider: "deepgram", model: "nova-3" },
  llm: { provider: "azure_openai", model: "gpt-5-mini" },
  tts: { provider: "elevenlabs", model: "eleven_flash_v2_5" },
  nc: null,
};

export const DEFAULT_STACK_LABELS = { stt: "Nova-3", llm: "GPT-5 Mini", tts: "Flash v2.5" } as const;

/** Per-minute price of the default stack from the launch catalog, for static marketing copy. */
export const SEED_PER_MINUTE_MICROS: bigint = toMicros(priceQuote(catalogV1, DEFAULT_STACK).per_minute_total_usd) ?? 105_000n;

/** Whole minutes of calls a balance pays for at a per-minute price (never negative). */
export function talkMinutes(balanceMicros: bigint, perMinuteMicros: bigint): number {
  if (perMinuteMicros <= 0n || balanceMicros <= 0n) return 0;
  return Number(balanceMicros / perMinuteMicros);
}
