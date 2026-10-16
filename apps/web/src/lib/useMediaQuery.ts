import { useSyncExternalStore } from "react";

/** True while the media query matches; false where matchMedia is missing (tests, old browsers). */
export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (onChange) => {
      const mql = window.matchMedia?.(query);
      mql?.addEventListener?.("change", onChange);
      return () => mql?.removeEventListener?.("change", onChange);
    },
    () => Boolean(window.matchMedia?.(query).matches),
    () => false,
  );
}

/** The inspector pane is a side column at 1280px and up (docs/DESIGN.md section 5). */
export const WIDE = "(min-width: 1280px)";
