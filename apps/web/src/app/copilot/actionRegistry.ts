/**
 * Page actions the voice copilot may run (006 T082, FR-031). A page registers what it can do with
 * `useRegisterVoiceActions`; only registered keys are sent to the server, and only a key the server
 * returned after validation is run, exactly as if its button were pressed. Highlights name a key a
 * page marked with `data-copilot-key`, never a selector.
 */
import { useEffect, useRef } from "react";

export interface VoiceAction {
  key: string;
  label: string;
  params_schema?: Record<string, unknown> | null;
  run: (params: Record<string, unknown> | null) => void;
}

const actions = new Map<string, VoiceAction>();

export function registeredActions(): { key: string; label: string; params_schema: Record<string, unknown> | null }[] {
  return [...actions.values()].map(({ key, label, params_schema }) => ({ key, label, params_schema: params_schema ?? null }));
}

export function runAction(key: string, params: Record<string, unknown> | null): boolean {
  const action = actions.get(key);
  if (!action) return false;
  action.run(params);
  return true;
}

/** Registers `list` while the calling page is mounted; the latest callbacks are always used. */
export function useRegisterVoiceActions(list: VoiceAction[]) {
  const latest = useRef(list);
  latest.current = list;
  const keys = list.map((a) => a.key).join("|");
  useEffect(() => {
    const mine = latest.current.map((a) => a.key);
    for (const a of latest.current) {
      actions.set(a.key, { ...a, run: (p) => latest.current.find((x) => x.key === a.key)?.run(p) });
    }
    return () => mine.forEach((k) => actions.delete(k));
  }, [keys]);
}

export function highlightableElements(): string[] {
  return [...document.querySelectorAll<HTMLElement>("[data-copilot-key]")].map((el) => el.dataset.copilotKey!).filter(Boolean);
}

export function highlight(key: string) {
  const el = document.querySelector<HTMLElement>(`[data-copilot-key="${CSS.escape(key)}"]`);
  if (!el) return;
  el.scrollIntoView({ behavior: "smooth", block: "center" });
  el.animate([{ boxShadow: "0 0 0 0 var(--halo)" }, { boxShadow: "0 0 0 8px var(--halo-soft)" }, { boxShadow: "0 0 0 0 var(--halo-soft)" }], {
    duration: 1400,
    iterations: 2,
    easing: "ease-out",
  });
}
