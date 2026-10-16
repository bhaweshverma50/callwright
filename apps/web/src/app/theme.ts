/**
 * Theme preference: system (default), light or dark. index.html applies it before first paint;
 * this module keeps `data-theme` in sync afterwards and follows OS changes while on "system".
 */
import { useSyncExternalStore } from "react";

export type ThemePref = "system" | "light" | "dark";
const KEY = "cw.theme";
const listeners = new Set<() => void>();

function readPref(): ThemePref {
  try {
    const v = localStorage.getItem(KEY);
    return v === "light" || v === "dark" ? v : "system";
  } catch {
    return "system";
  }
}

let pref: ThemePref = typeof window === "undefined" ? "system" : readPref();

const systemDark = () => typeof window !== "undefined" && window.matchMedia?.("(prefers-color-scheme: dark)").matches;

export function resolvedTheme(p: ThemePref = pref): "light" | "dark" {
  return p === "system" ? (systemDark() ? "dark" : "light") : p;
}

function apply() {
  document.documentElement.setAttribute("data-theme", resolvedTheme());
  listeners.forEach((l) => l());
}

export function setThemePref(next: ThemePref) {
  pref = next;
  try {
    if (next === "system") localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, next);
  } catch {
    /* storage blocked: preference lasts for this page only */
  }
  apply();
}

export function initTheme() {
  apply();
  window.matchMedia?.("(prefers-color-scheme: dark)").addEventListener?.("change", () => {
    if (pref === "system") apply();
  });
}

export function useThemePref(): ThemePref {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => pref,
    () => pref,
  );
}
