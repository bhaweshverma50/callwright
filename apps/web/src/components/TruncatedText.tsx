import { Info } from "lucide-react";
import { useCallback, useLayoutEffect, useRef, useState, type ElementType, type ReactNode } from "react";
import { cn, focusRing } from "./cn";
import { Tooltip } from "./Tooltip";

/**
 * Single-line text that ends in an ellipsis when it does not fit. The full text shows in a tooltip
 * on hover and keyboard focus, but only while it is actually cut off, so short values stay quiet.
 *
 * Inside a link, button or menu trigger pass `focusable={false}`: the parent already takes focus
 * and carries the full text as its accessible name, so the text must not add a second tab stop.
 * Pass `tooltip={false}` when an enclosing tooltip already shows the full text.
 */
export function TruncatedText({
  children,
  title,
  as: Tag = "span",
  className,
  side = "top",
  focusable = true,
  tooltip = true,
}: {
  children: ReactNode;
  /** Full text for the tooltip when children are not plain text. */
  title?: ReactNode;
  as?: ElementType;
  className?: string;
  side?: "top" | "right" | "bottom" | "left";
  focusable?: boolean;
  tooltip?: boolean;
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
    <Tooltip content={title ?? children} side={side} enabled={cut && tooltip}>
      <Tag
        ref={ref}
        onPointerEnter={measure}
        onFocus={measure}
        tabIndex={cut && focusable && tooltip ? 0 : undefined}
        className={cn("block min-w-0 truncate", cut && focusable && tooltip && cn("rounded-inline", focusRing), className)}
      >
        {children}
      </Tag>
    </Tooltip>
  );
}

/**
 * Small info icon that explains a term or a number. Focusable, so keyboard users get the text too;
 * the hit area reaches past the 14px glyph so it is easy to hover. The explanation adds detail:
 * anything the reader must know stays in the visible text next to it.
 */
export function InfoTip({
  children,
  label = "More information",
  side = "top",
  className,
}: {
  children: ReactNode;
  label?: string;
  side?: "top" | "right" | "bottom" | "left";
  className?: string;
}) {
  return (
    <Tooltip side={side} content={<span className="block font-normal">{children}</span>}>
      <button
        type="button"
        aria-label={label}
        className={cn(
          "relative inline-grid size-4 shrink-0 cursor-help place-items-center rounded-full align-[-3px] text-fg-3 transition-colors duration-150",
          "before:absolute before:-inset-1.5 before:content-[''] hover:text-accent-text data-[state=delayed-open]:text-accent-text data-[state=instant-open]:text-accent-text",
          focusRing,
          className,
        )}
      >
        <Info className="size-3.5" strokeWidth={2} aria-hidden />
      </button>
    </Tooltip>
  );
}
