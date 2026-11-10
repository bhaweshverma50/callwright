/**
 * Lazy feature credentials (FR-020, T098). Optional features (voice copilot STT key, web test
 * call room token, analytics assistant session) get their credential the first time the user
 * actually uses the feature, never on page load. The hook does nothing until the returned
 * function is called, and reuses the credential until 15 s before it expires.
 *
 * ESLint (eslint.config.js) rejects calls to this hook in the shell and router files.
 */
import { useCallback, useRef } from "react";

export function useLazyToken<T extends { expires_at: string }>(fetcher: () => Promise<T>): () => Promise<T> {
  const cache = useRef<T | null>(null);
  return useCallback(async () => {
    const hit = cache.current;
    if (hit && Date.parse(hit.expires_at) - Date.now() > 15_000) return hit;
    const fresh = await fetcher();
    cache.current = fresh;
    return fresh;
  }, [fetcher]);
}
