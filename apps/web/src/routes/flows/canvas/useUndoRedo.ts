import { useCallback, useRef, useState } from "react";

/**
 * Undo and redo over whole graph snapshots (FR-005: at least 50 steps). `set` records the state
 * before a change. A drag moves nodes on the canvas only and writes the document once when it
 * ends, so a whole move is one step.
 * History lives in refs (not inside state updaters) so StrictMode's double calls stay harmless.
 */
export function useUndoRedo<T>(initial: T, limit = 50) {
  const [present, setPresent] = useState(initial);
  const current = useRef(initial);
  const past = useRef<T[]>([]);
  const future = useRef<T[]>([]);

  const show = useCallback((value: T) => {
    current.current = value;
    setPresent(value);
  }, []);

  const set = useCallback(
    (next: T | ((prev: T) => T), record = true) => {
      const prev = current.current;
      const value = typeof next === "function" ? (next as (p: T) => T)(prev) : next;
      if (value === prev) return;
      if (record) {
        past.current = [...past.current.slice(-(limit - 1)), prev];
        future.current = [];
      }
      show(value);
    },
    [limit, show],
  );

  const undo = useCallback(() => {
    const last = past.current.at(-1);
    if (last === undefined) return;
    past.current = past.current.slice(0, -1);
    future.current = [current.current, ...future.current];
    show(last);
  }, [show]);

  const redo = useCallback(() => {
    const [next, ...rest] = future.current;
    if (next === undefined) return;
    future.current = rest;
    past.current = [...past.current, current.current];
    show(next);
  }, [show]);

  const reset = useCallback(
    (value: T) => {
      past.current = [];
      future.current = [];
      show(value);
    },
    [show],
  );

  return { present, set, undo, redo, reset, canUndo: past.current.length > 0, canRedo: future.current.length > 0 };
}
