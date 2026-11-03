/**
 * Display helpers for scheduled callbacks (spec 011). Times are shown in the recipient's zone,
 * since that is the time the caller agreed to: "Tue 4 Nov, 5:00 pm" with a short zone label.
 */
import type { Callback, CallbackStatus } from "../../../api/callbacks";
import type { Tone } from "../../../components";

export const CALLBACK_STATUS_LABELS: Record<CallbackStatus, string> = {
  scheduled: "Scheduled",
  placing: "Placing",
  placed: "Placed",
  failed: "Failed",
  cancelled: "Cancelled",
};

export const CALLBACK_STATUS_TONES: Record<CallbackStatus, Tone> = {
  scheduled: "accent",
  placing: "accent",
  placed: "success",
  failed: "danger",
  cancelled: "neutral",
};

const partsFmt = new Intl.DateTimeFormat("en-GB", {
  weekday: "short",
  day: "numeric",
  month: "short",
  hour: "numeric",
  minute: "2-digit",
  hour12: true,
  timeZone: "UTC",
});

/** "Tue 4 Nov, 5:00 pm" from parts, so engines that add a comma after the weekday read the same. */
function label(d: Date, fmt: Intl.DateTimeFormat = partsFmt): string {
  const part = (type: Intl.DateTimeFormatPartTypes) => fmt.formatToParts(d).find((p) => p.type === type)?.value ?? "";
  return `${part("weekday")} ${part("day")} ${part("month")}, ${part("hour")}:${part("minute")} ${part("dayPeriod").toLowerCase()}`;
}

/** The wall-clock parts of `local_time` ("2026-11-04T17:00:00") as a UTC date, so formatting never shifts it. */
function wallClock(local: string): Date | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(local);
  if (!m) return null;
  return new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]), Number(m[4]), Number(m[5])));
}

/** "Tue 4 Nov, 5:00 pm" in the recipient's wall-clock time. */
export function localTimeLabel(cb: Pick<Callback, "local_time" | "scheduled_at" | "timezone">): string {
  const d = wallClock(cb.local_time);
  if (d) return label(d);
  // Fall back to the UTC instant in the recipient's zone.
  try {
    return label(
      new Date(cb.scheduled_at),
      new Intl.DateTimeFormat("en-GB", {
        weekday: "short",
        day: "numeric",
        month: "short",
        hour: "numeric",
        minute: "2-digit",
        hour12: true,
        timeZone: cb.timezone,
      }),
    );
  } catch {
    return cb.local_time;
  }
}

/**
 * Phone numbers grouped for reading: North American numbers as "+1 415 555 0100", India as
 * "+91 98200 12345", London as "+44 20 7946 0958". Anything else is shown as stored.
 */
export function phoneLabel(value: string | null | undefined): string {
  if (!value) return "";
  const groups: [RegExp, string][] = [
    [/^\+1(\d{3})(\d{3})(\d{4})$/, "+1 $1 $2 $3"],
    [/^\+91(\d{5})(\d{5})$/, "+91 $1 $2"],
    [/^\+44(20)(\d{4})(\d{4})$/, "+44 $1 $2 $3"],
    [/^\+44(\d{4})(\d{6})$/, "+44 $1 $2"],
  ];
  for (const [re, out] of groups) if (re.test(value)) return value.replace(re, out);
  return value;
}

const shortDate = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short" });
/** "16 Oct" in the viewer's zone, for when something happened. */
export const dayLabel = (iso: string) => shortDate.format(new Date(iso));

/**
 * A short zone name for the instant: "EDT", "BST", "IST", "AEDT". Locales name different zones,
 * so a few English ones are tried; when none has a letter abbreviation the city is used ("Lagos").
 */
export function zoneLabel(timezone: string, at: string): string {
  const instant = new Date(at);
  for (const locale of ["en-US", "en-GB", "en-IN", "en-AU"]) {
    try {
      const name = new Intl.DateTimeFormat(locale, { timeZone: timezone, timeZoneName: "short" })
        .formatToParts(instant)
        .find((p) => p.type === "timeZoneName")?.value;
      if (name && /^[A-Z]{2,5}$/.test(name)) return name;
    } catch {
      break;
    }
  }
  return timezone.split("/").pop()?.replace(/_/g, " ") ?? timezone;
}

/** Why a callback was not placed, in plain words. */
const FAILURE_TEXT: Record<string, string> = {
  dnc_listed: "The number is on your do-not-call list.",
  outside_calling_hours: "The time fell outside your calling hours.",
  missed: "It could not be placed within 30 minutes of the agreed time.",
  insufficient_credit: "Your balance was too low to place the call.",
  concurrency_limit: "Your workspace was at its concurrent-call limit.",
  from_number_not_active: "The number it calls from is no longer active.",
  no_outbound_agent: "The calling number has no outbound agent.",
  agent_not_published: "The agent has no published version to take the call.",
};

/** Short form for the list. */
const FAILURE_SHORT: Record<string, string> = {
  dnc_listed: "On the do-not-call list",
  outside_calling_hours: "Outside calling hours",
  missed: "Missed the time window",
  insufficient_credit: "Balance too low",
  concurrency_limit: "Concurrent-call limit reached",
  from_number_not_active: "Calling number not active",
  no_outbound_agent: "No outbound agent",
  agent_not_published: "Agent not published",
};

export function failureText(cb: Pick<Callback, "failure_reason" | "failure_detail">): string {
  return (cb.failure_reason && FAILURE_TEXT[cb.failure_reason]) || cb.failure_detail || "The call could not be placed.";
}

export function failureShort(cb: Pick<Callback, "failure_reason" | "failure_detail">): string {
  return (cb.failure_reason && FAILURE_SHORT[cb.failure_reason]) || "Not placed";
}

/** Address of a call drawer on the current page: keeps the list's own parameters, drops the drawer tab. */
export function callDrawerSearch(current: URLSearchParams, callId: string): string {
  const p = new URLSearchParams(current);
  p.set("call", callId);
  p.delete("tab");
  return `?${p.toString()}`;
}
