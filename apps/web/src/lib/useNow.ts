import { useSyncExternalStore } from "react";

/**
 * One shared one-second clock for every ticking duration on screen, so ten live rows cost one
 * timer, not ten. It runs only while something subscribes with `active` true.
 */
const listeners = new Set<() => void>();
/** Whole seconds, so the snapshot is stable between ticks even before the timer starts. */
const second = () => Math.floor(Date.now() / 1_000) * 1_000;
let now = second();
let timer: ReturnType<typeof setInterval> | undefined;

function subscribe(fn: () => void) {
  listeners.add(fn);
  if (!timer) {
    now = second();
    timer = setInterval(() => {
      now = second();
      listeners.forEach((l) => l());
    }, 1_000);
  }
  return () => {
    listeners.delete(fn);
    if (!listeners.size && timer) {
      clearInterval(timer);
      timer = undefined;
    }
  };
}

const idle = () => () => {};

/** `Date.now()` that re-renders every second while `active`; a fixed value otherwise. */
export function useNow(active = true): number {
  return useSyncExternalStore(
    active ? subscribe : idle,
    () => (active ? (timer ? now : second()) : 0),
    () => 0,
  );
}
