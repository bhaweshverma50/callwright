/**
 * The spec 001 reference call (US3): 271 s, 102,348 input tokens, 745 output tokens, 2,555 TTS
 * characters on Deepgram Nova-3, GPT-5 Mini and ElevenLabs Flash v2.5. Priced with the same
 * engine the mock API uses, so the marketing examples can never disagree with the calculator.
 */
import type { CostBreakdown } from "../../api/types";
import { catalogV1 } from "../../lib/catalogSeed";
import { priceQuote } from "../../lib/pricing";

export const REFERENCE_USAGE = {
  duration_ms: 271_000,
  llm_input_tokens: 102_348,
  llm_output_tokens: 745,
  tts_chars: 2_555,
};

export const referenceBreakdown: CostBreakdown = priceQuote(
  catalogV1,
  {
    stt: { provider: "deepgram", model: "nova-3" },
    llm: { provider: "azure_openai", model: "gpt-5-mini" },
    tts: { provider: "elevenlabs", model: "eleven_flash_v2_5" },
    nc: null,
  },
  REFERENCE_USAGE,
).call!;
