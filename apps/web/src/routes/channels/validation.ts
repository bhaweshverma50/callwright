/**
 * Client-side mirrors of the channel rules the API enforces (010 T081, T085, research R12, R14),
 * so the dialogs can point at the field before sending anything. The server stays the authority:
 * its field errors are mapped onto the same fields.
 */

export const E164 = /^\+[1-9]\d{6,14}$/;
export const E164_EXAMPLE = "+14155550123";

export function e164Error(value: string, label = "number"): string | null {
  const v = value.trim();
  if (!v) return `Enter the ${label}.`;
  if (!v.startsWith("+")) return `Start with + and the country code, for example ${E164_EXAMPLE}.`;
  if (/\s|-|\(|\)/.test(v)) return `Digits only after the +, for example ${E164_EXAMPLE}.`;
  if (!E164.test(v)) return `Use E.164: + and 7 to 15 digits, for example ${E164_EXAMPLE}.`;
  return null;
}

const LABEL = /^(?!-)[a-z0-9-]{1,63}(?<!-)$/i;
const IPV4 = /^(25[0-5]|2[0-4]\d|1?\d?\d)(\.(25[0-5]|2[0-4]\d|1?\d?\d)){3}$/;

/** The address without a leading `sip:`/`sips:` (what the server stores). */
export function stripScheme(value: string): string {
  return value.trim().replace(/^sips?:/i, "");
}

export function terminationError(value: string): string | null {
  const raw = stripScheme(value);
  if (!raw) return "Enter the carrier's termination address, for example trunk.example.com:5060.";
  if (/[@;/?]/.test(raw)) return "Enter only a host and optional port: no user part (@), path or parameters.";
  let host = raw;
  let port: string | null = null;
  if (raw.startsWith("[")) {
    const end = raw.indexOf("]");
    if (end === -1) return "A bracketed IPv6 address must end with ].";
    host = raw.slice(1, end);
    const rest = raw.slice(end + 1);
    if (rest && !rest.startsWith(":")) return "Enter only a host and optional port.";
    port = rest ? rest.slice(1) : null;
    if (!/^[0-9a-f:.]+$/i.test(host) || !host.includes(":")) return "The address in brackets is not a valid IPv6 address.";
  } else {
    const parts = raw.split(":");
    if (parts.length > 2) return "Put IPv6 addresses in brackets, for example [2001:db8::10]:5060.";
    host = parts[0]!;
    port = parts.length === 2 ? parts[1]! : null;
    const isIp = /^[\d.]+$/.test(host);
    if (isIp ? !IPV4.test(host) : host.length > 253 || !host.split(".").every((l) => LABEL.test(l))) {
      return "Enter a host name, an IPv4 address or a bracketed IPv6 address.";
    }
  }
  if (port !== null && (!/^\d+$/.test(port) || Number(port) < 1 || Number(port) > 65535)) return "The port must be a number from 1 to 65535.";
  return null;
}

/** One range per line or comma. Returns the list and the first problem. */
export function parseCidrs(text: string): { cidrs: string[]; error: string | null } {
  const cidrs = text
    .split(/[\s,]+/)
    .map((s) => s.trim())
    .filter(Boolean);
  if (cidrs.length > 20) return { cidrs, error: "At most 20 address ranges." };
  for (const c of cidrs) {
    const [ip, bits, extra] = c.split("/");
    const v6 = ip!.includes(":");
    const max = v6 ? 128 : 32;
    const okIp = v6 ? /^[0-9a-f:.]+$/i.test(ip!) : IPV4.test(ip!);
    const okBits = bits === undefined || (/^\d+$/.test(bits) && Number(bits) <= max);
    if (!okIp || !okBits || extra !== undefined) return { cidrs, error: `${c} is not an IPv4 or IPv6 range, for example 203.0.113.0/24.` };
  }
  return { cidrs, error: null };
}

export function webhookUrlError(value: string): string | null {
  const v = value.trim();
  if (!v) return null;
  try {
    const u = new URL(v);
    if (u.protocol !== "https:" && u.protocol !== "http:") return "Use an https address.";
  } catch {
    return "Enter a full address, for example https://crm.example.com/callwright.";
  }
  return null;
}
