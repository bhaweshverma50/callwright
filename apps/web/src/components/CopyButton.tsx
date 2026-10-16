import { Check, Copy } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { IconButton } from "./Button";
import { cn } from "./cn";

/**
 * Copies a value (an id, a key) to the clipboard. Icon-only, so the tooltip and accessible name
 * say what it copies; after a copy the icon turns into a check for a moment and a polite live
 * region says "Copied" for screen readers.
 */
export function CopyButton({ value, label, className }: { value: string; label: string; className?: string }) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
    } catch {
      return; // clipboard blocked: nothing changes, so the check never claims a copy that failed
    }
    setCopied(true);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setCopied(false), 1600);
  };
  return (
    <>
      <IconButton label={label} onClick={copy} className={cn("size-7 shrink-0 [&_svg]:size-3.5", copied && "text-success-text", className)}>
        {copied ? <Check aria-hidden strokeWidth={2.5} /> : <Copy aria-hidden />}
      </IconButton>
      <span role="status" aria-live="polite" className="sr-only">
        {copied ? "Copied" : ""}
      </span>
    </>
  );
}
