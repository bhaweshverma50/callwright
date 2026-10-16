/**
 * Surcharge-risk heuristic for the cost card (FR-032, research R17). Every model turn re-sends the
 * system prompt, so a long prompt can push a typical minute past the model's input allowance (the
 * per-minute bundle from the quote) and the call is billed for more minutes than it lasts.
 *
 * Estimate: prompt tokens (about 4 tokens per 3 words) plus about 600 tokens of conversation
 * history per turn, times 5 turns in a typical minute of conversation.
 */
export const TURNS_PER_MINUTE = 5;
export const HISTORY_TOKENS_PER_TURN = 600;

export function countWords(text: string): number {
  return text.trim() ? text.trim().split(/\s+/).length : 0;
}

export function estimateTokens(text: string): number {
  return Math.ceil((countWords(text) * 4) / 3);
}

export interface SurchargeRisk {
  risk: boolean;
  /** Estimated input tokens in a typical minute. */
  perMinute: number;
  /** The allowance it is compared with (input tokens per minute). */
  bundle: number;
}

export function surchargeRisk(prompt: string, inputBundlePerMin: number | null | undefined): SurchargeRisk | null {
  if (!inputBundlePerMin) return null;
  const perMinute = (estimateTokens(prompt) + HISTORY_TOKENS_PER_TURN) * TURNS_PER_MINUTE;
  return { risk: perMinute > inputBundlePerMin, perMinute, bundle: inputBundlePerMin };
}
