import { clsx, type ClassValue } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

// Teach tailwind-merge the project radius names so `rounded-control` and `rounded-full` conflict.
const twMerge = extendTailwindMerge({ extend: { theme: { radius: ["control", "panel"] } } });

/** Class names with later Tailwind utilities winning over earlier ones (className overrides). */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Shared focus ring: 2px signal ring with offset matching the surface underneath. */
export const focusRing =
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring";
