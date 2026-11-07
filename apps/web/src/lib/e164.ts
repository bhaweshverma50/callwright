/**
 * Phone numbers in E.164 form (a plus, the country code and 7 to 15 digits), as the API stores
 * them for transfers, phone numbers, WhatsApp channels and outbound calls. The server stays the
 * authority; this check only points at the field early.
 */

export const E164 = /^\+[1-9]\d{6,14}$/;
export const E164_EXAMPLE = "+14155550123";

/** `label` names the field in the empty message ("Enter the destination number."). */
export function e164Error(value: string | undefined, label = "number"): string | null {
  const v = (value ?? "").trim();
  if (!v) return `Enter the ${label}.`;
  if (!v.startsWith("+")) return `Start with + and the country code, for example ${E164_EXAMPLE}.`;
  if (/\s|-|\(|\)/.test(v)) return `Digits only after the +, for example ${E164_EXAMPLE}.`;
  if (!E164.test(v)) return `Use E.164: + and 7 to 15 digits, for example ${E164_EXAMPLE}.`;
  return null;
}
