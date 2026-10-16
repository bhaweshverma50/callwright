/**
 * Lazy feature credentials (FR-020, T098). Optional features (voice copilot STT key, web test
 * call room token, analytics assistant session) get their credential the first time the user
 * actually uses the feature, never on page load. The hook does nothing until `request()` is
 * called and caches the token until it expires.
 *
 * ESLint (eslint.config.js) rejects calls to this hook in the shell and router files.
 */
import { useCallback, useRef, useState } from "react";

export type LazyFeature = "voice_copilot" | "web_call" | "analytics_chat";

export interface LazyToken {
  token: string;
  expires_at: number;
}

export function useLazyToken(_feature: LazyFeature, fetcher: () => Promise<LazyToken>) {
  const cache = useRef<LazyToken | null>(null);
  const [state, setState] = useState<"idle" | "loading" | "ready" | "error">("idle");

  const request = useCallback(async () => {
    const hit = cache.current;
    if (hit && hit.expires_at - Date.now() > 15_000) return hit.token;
    setState("loading");
    try {
      const fresh = await fetcher();
      cache.current = fresh;
      setState("ready");
      return fresh.token;
    } catch (e) {
      setState("error");
      throw e;
    }
  }, [fetcher]);

  return { state, request };
}
