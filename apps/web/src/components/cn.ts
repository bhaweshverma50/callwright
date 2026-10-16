import { clsx, type ClassValue } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

// Teach tailwind-merge the project radius and shadow names so overrides conflict correctly.
const twMerge = extendTailwindMerge({
  extend: {
    theme: { radius: ["inline", "control", "panel", "feature"], shadow: ["1", "2", "pop", "glow"] },
  },
});

/** Class names with later Tailwind utilities winning over earlier ones (className overrides). */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Shared focus ring: 2px cobalt ring with a 2px offset, visible on every surface. */
export const focusRing = "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring";
