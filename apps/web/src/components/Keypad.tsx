import { useEffect, useState } from "react";
import { cn, focusRing } from "./cn";

const KEYS: [string, string][] = [
  ["1", ""],
  ["2", "ABC"],
  ["3", "DEF"],
  ["4", "GHI"],
  ["5", "JKL"],
  ["6", "MNO"],
  ["7", "PQRS"],
  ["8", "TUV"],
  ["9", "WXYZ"],
  ["*", ""],
  ["0", "+"],
  ["#", ""],
];

/**
 * Phone keypad for a test call (spec 003 T099). Each press goes to the agent as DTMF, the same as
 * a caller typing on a phone. Typing digits, * or # on the keyboard works while it is open.
 */
export function Keypad({ onPress, className }: { onPress: (digit: string) => void; className?: string }) {
  const [typed, setTyped] = useState("");
  const press = (d: string) => {
    setTyped((t) => (t + d).slice(-16));
    onPress(d);
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (e.metaKey || e.ctrlKey || e.altKey || el?.closest("input, textarea, [contenteditable=true]")) return;
      if (/^[0-9*#]$/.test(e.key)) {
        e.preventDefault();
        press(e.key);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [onPress]);

  return (
    <div className={cn("flex flex-col gap-3", className)}>
      <p aria-live="polite" className="h-7 text-center font-mono text-[18px] tracking-[0.2em] text-fg tnum">
        {typed || <span className="text-[13px] tracking-normal text-fg-3">Type on the keypad or keyboard</span>}
      </p>
      <div role="group" aria-label="Keypad" className="mx-auto grid w-full max-w-[15rem] grid-cols-3 gap-2">
        {KEYS.map(([d, letters]) => (
          <button
            key={d}
            type="button"
            aria-label={d === "*" ? "Star" : d === "#" ? "Pound" : d}
            onClick={() => press(d)}
            className={cn(
              "flex h-12 cursor-pointer flex-col items-center justify-center rounded-panel bg-surface-2 leading-none transition-colors duration-150 hover:bg-surface-3 active:scale-[0.97]",
              focusRing,
            )}
          >
            <span className="text-[18px] font-medium text-fg">{d}</span>
            {letters && <span className="mt-0.5 text-[9.5px] tracking-[0.12em] text-fg-3">{letters}</span>}
          </button>
        ))}
      </div>
      <p className="text-center text-[12px] leading-relaxed text-fg-3">The agent reads key presses only when keypad input is on in Advanced.</p>
    </div>
  );
}
