/** A fresh key per user action, so a double click or a retried request creates one record (FR-038). */
export function idempotencyKey(): string {
  try {
    return crypto.randomUUID();
  } catch {
    return `k-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
  }
}
