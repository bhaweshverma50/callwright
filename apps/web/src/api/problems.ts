/**
 * Problem to plain message (FR-019, T095). The UI never shows status codes, transport errors or
 * server text that could carry internals; every message here is written for operators.
 */
import { isApiError } from "./errors";
import type { Problem } from "./types";

function minutesFrom(seconds?: number): string {
  if (!seconds || seconds <= 60) return "a minute";
  const m = Math.ceil(seconds / 60);
  return `${m} minutes`;
}

const BY_CODE: Record<string, (p: Problem, kind: string) => string> = {
  not_found: (_p, kind) => `This ${kind} was not found. It may have been deleted, or the link is wrong.`,
  invalid_credentials: () => "That email and password do not match an account.",
  email_unverified: () => "Verify your email first. We can send the link again.",
  insufficient_credit: () => "Your balance is too low for this. Add funds to continue.",
  concurrency_limit: () => "Your workspace is at its concurrent-call limit. Try again when a call ends.",
  link_invalid: () => "This link has expired or was already used.",
  token_invalid: () => "This link has expired or was already used.",
  pricing_unavailable: () => "A selected component has no price yet, so this cannot run on live traffic.",
  network: () => "Cannot reach Callwright right now. Check your connection and try again.",
  // 022 Google connections and Drive sources.
  oauth_state_invalid: () => "This sign-in link expired or was started by someone else. Start again from Connections.",
  oauth_declined: () => "Google access was not granted, so no connection was made.",
  oauth_exchange_failed: () => "Google refused the sign-in. Try connecting again.",
  oauth_scope_missing: () => "Read-only Google Drive access is required. Connect again and leave the Google Drive box ticked.",
  // The server names the account the connection belongs to (masked), so say that.
  oauth_account_mismatch: (p) => p.detail ?? "Sign in with the Google account this connection belongs to, or add a new connection.",
  connection_revoked: () => "Google access was revoked or expired. Reconnect the Google account in Connections.",
  connection_in_use: () => "Remove the knowledge sources that use this connection first.",
  connector_unavailable: () => "Google Drive is not set up on this Callwright server yet. Ask your administrator to add the Google settings.",
  google_unavailable: () => "Google did not answer or rate limited the request. Try again in a minute.",
  source_exists: () => "This folder already syncs into this knowledge base.",
  sync_running: () => "A sync of this source is already running.",
  nothing_held: () => "No archiving is waiting for a decision any more.",
  managed_by_source: () => "This document syncs from Google Drive. Change it in Drive and it updates here.",
};

/**
 * Message for a failed request. `recordKind` names what the page loads ("agent", "transaction")
 * so not-found reads naturally.
 */
export function problemMessage(err: unknown, recordKind = "record"): string {
  if (!isApiError(err)) return "Something went wrong. Try again in a moment.";
  const p = err.problem;
  const byCode = p.code ? BY_CODE[p.code] : undefined;
  if (byCode) return byCode(p, recordKind);
  if (err.status === 0) return BY_CODE.network!(p, recordKind);
  if (err.status === 402) return BY_CODE.insufficient_credit!(p, recordKind);
  if (err.status === 404) return BY_CODE.not_found!(p, recordKind);
  if (err.status === 429) return `Too many attempts. Try again in ${minutesFrom(p.retry_after_s)}.`;
  if (err.status === 422) return "Some fields need attention.";
  if (err.status === 401) return "Your session ended. Sign in again to continue.";
  if (err.status === 403) return "You do not have access to this.";
  if (err.status >= 500) {
    return p.trace_id
      ? `Something went wrong on our side. If it keeps happening, contact support with reference ${p.trace_id}.`
      : "Something went wrong on our side. Try again in a moment.";
  }
  return "That did not work. Check the details and try again.";
}

/**
 * Message for a toast or an inline error: the server's own `detail` when it wrote one for people
 * (except for credit, which always says how to add funds), otherwise problemMessage.
 */
export function problemText(err: unknown, recordKind = "record"): string {
  if (isApiError(err) && err.status !== 402 && err.code !== "insufficient_credit" && err.problem.detail) return err.problem.detail;
  return problemMessage(err, recordKind);
}

/** Field errors keyed by the last segment of the JSON pointer ("/amount_usd" -> "amount_usd"). */
export function fieldErrors(err: unknown): Record<string, string> {
  if (!isApiError(err)) return {};
  const out: Record<string, string> = {};
  for (const fe of err.problem.errors ?? []) {
    const key = fe.pointer.split("/").filter(Boolean).pop() ?? "";
    out[key] ??= fe.message;
  }
  return out;
}

export function traceIdOf(err: unknown): string | undefined {
  return isApiError(err) ? err.traceId : undefined;
}
