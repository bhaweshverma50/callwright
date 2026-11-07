/**
 * Paid actions (spec 008, FR-030): every paid POST carries an `Idempotency-Key`. One key belongs
 * to one user action: a retry of the same action (after a network error or a 5xx) reuses it, so
 * the server creates and charges one record; a new action gets a new key.
 */
import { useCallback, useRef } from "react";
import { idempotencyKey } from "../lib/idempotency";
import { isApiError } from "./errors";

export interface ActionKey {
  /** The key for the current action; the same value until `reset()`. */
  current: () => string;
  /** Call after the action succeeded or its inputs changed, so the next attempt is a new action. */
  reset: () => void;
}

export function useActionKey(): ActionKey {
  const ref = useRef<string | null>(null);
  const current = useCallback(() => (ref.current ??= idempotencyKey()), []);
  const reset = useCallback(() => {
    ref.current = null;
  }, []);
  return { current, reset };
}

/** 402 or `insufficient_credit`: the balance is at or below zero. */
export function isInsufficientCredit(err: unknown): boolean {
  return isApiError(err) && (err.status === 402 || err.problem.code === "insufficient_credit");
}

/** A retry is worth reusing the key for: the request may have reached the server. */
export function isRetryable(err: unknown): boolean {
  return !isApiError(err) || err.status === 0 || err.status >= 500;
}
