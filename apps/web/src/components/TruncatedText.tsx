import { Info } from "lucide-react";
import { useCallback, useLayoutEffect, useRef, useState, type ElementType, type ReactNode } from "react";
import { cn } from "./cn";
import { Tooltip } from "./Tooltip";

/**
 * Single-line text that ends in an ellipsis when it does not fit. The full text shows in a tooltip
 * on hover and keyboard focus, but only while it is actually cut off, so short values stay quiet.
 */
export function TruncatedText({
  children,
  title,
  as: Tag = "span",
  className,
  side = "top",
}: {
  children: ReactNode;
  /** Full text for the tooltip when children are not plain text. */
  title?: ReactNode;
  as?: ElementType;
  className?: string;
  side?: "top" | "right" | "bottom" | "left";
}) {
  const ref = useRef<HTMLElement | null>(null);
  const [cut, setCut] = useState(false);
  const measure = useCallback(() => {
    const el = ref.current;
    if (el) setCut(el.scrollWidth > el.clientWidth + 1);
  }, []);
  // Know whether the text is cut before the pointer arrives, and keep knowing as the layout resizes.
  useLayoutEffect(() => {
    measure();
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [measure, children]);
  return (
    <Tooltip content={<span className="block max-w-[44ch] break-words">{title ?? children}</span>} side={side} enabled={cut}>
      <Tag
        ref={ref}
        onPointerEnter={measure}
        onFocus={measure}
        tabIndex={cut ? 0 : undefined}
        className={cn("block min-w-0 truncate", cut && "cursor-help", className)}
      >
        {children}
      </Tag>
    </Tooltip>
  );
}

/** Small info icon that explains a term or a number. Focusable, so keyboard users get the text too. */
export function InfoTip({ children, label = "More information", className }: { children: ReactNode; label?: string; className?: string }) {
  return (
    <Tooltip content={<span className="block max-w-[36ch] font-normal leading-snug">{children}</span>}>
      <button
        type="button"
        aria-label={label}
        className={cn(
          "inline-grid size-4 shrink-0 place-items-center rounded-full align-[-2px] text-fg-3 transition-colors hover:text-fg-2",
          "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
          className,
        )}
      >
        <Info className="size-3.5" aria-hidden />
      </button>
    </Tooltip>
  );
}
