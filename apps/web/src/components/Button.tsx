import { Slot, Slottable } from "@radix-ui/react-slot";
import { forwardRef, type ButtonHTMLAttributes, type MouseEvent, type PointerEvent, type ReactNode } from "react";
import { cn, focusRing } from "./cn";
import { useRipple } from "./motion";
import { Tooltip } from "./Tooltip";

type Variant = "primary" | "secondary" | "ghost" | "danger" | "link";
type Size = "sm" | "md" | "lg";

const variants: Record<Variant, string> = {
  primary: cn(
    "bg-accent text-white shadow-1 hover:bg-accent-hover",
    "disabled:bg-surface-3 disabled:text-fg-3 disabled:shadow-none aria-disabled:bg-surface-3 aria-disabled:text-fg-3 aria-disabled:shadow-none",
  ),
  secondary: cn(
    "bg-surface text-fg border border-line-strong hover:border-accent/60 hover:bg-accent-soft/40 disabled:text-fg-3 disabled:border-line disabled:bg-surface",
    "aria-disabled:text-fg-3 aria-disabled:border-line aria-disabled:bg-surface",
  ),
  ghost: "text-fg-2 hover:text-fg hover:bg-surface-3 disabled:text-fg-3 disabled:bg-transparent aria-disabled:text-fg-3 aria-disabled:bg-transparent",
  danger:
    "bg-danger-solid text-white hover:brightness-110 disabled:bg-surface-3 disabled:text-fg-3 aria-disabled:bg-surface-3 aria-disabled:text-fg-3",
  link: "link-underline text-accent-text px-0 h-auto rounded-inline",
};

const sizes: Record<Size, string> = {
  sm: "h-8 px-3 text-[13px] gap-1.5 [&_svg]:size-3.5",
  md: "h-9 px-3.5 text-[13px] gap-2 [&_svg]:size-4",
  lg: "h-11 px-5 text-[14px] gap-2 [&_svg]:size-[18px]",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  /** Shows a pending indicator and blocks clicks; keeps the label for screen readers. A pending
   * button stays focusable (`aria-disabled`, not `disabled`) so keyboard focus is not dropped on
   * the page body while the action runs (002 T085). */
  pending?: boolean;
  /** Icon before the label. */
  icon?: ReactNode;
  asChild?: boolean;
}

/**
 * Buttons. Primary is the one solid cobalt action per view, a shade darker on hover, with a quick
 * press scale and a ripple. Labels name the action; no arrow glyph after the text.
 */
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", pending = false, icon, asChild, className, children, disabled, onPointerDown, onClick, ...rest },
  ref,
) {
  // Pending alone keeps the element enabled (and focused) but inert to clicks.
  const softDisabled = pending && !disabled && !asChild;
  const Comp = asChild ? Slot : "button";
  const { onPointerDown: ripple, ripples } = useRipple();
  return (
    <Comp
      ref={ref}
      className={cn(
        "relative inline-flex shrink-0 cursor-pointer select-none items-center justify-center overflow-hidden whitespace-nowrap rounded-control font-medium",
        "transition-[background-color,border-color,color,box-shadow,transform] duration-150",
        "active:scale-[var(--press-scale)] active:duration-[var(--press-duration)]",
        "disabled:cursor-not-allowed disabled:active:scale-100 aria-disabled:cursor-not-allowed aria-disabled:active:scale-100",
        focusRing,
        variants[variant],
        variant !== "link" && sizes[size],
        className,
      )}
      disabled={asChild ? undefined : disabled || undefined}
      aria-disabled={softDisabled || undefined}
      aria-busy={pending || undefined}
      onClick={(e: MouseEvent<HTMLButtonElement>) => {
        if (softDisabled) {
          e.preventDefault();
          return;
        }
        onClick?.(e);
      }}
      onPointerDown={(e: PointerEvent<HTMLButtonElement>) => {
        if (variant !== "link" && !softDisabled) ripple(e);
        onPointerDown?.(e);
      }}
      {...(asChild ? {} : { type: rest.type ?? "button" })}
      {...rest}
    >
      {pending ? <PendingDots /> : icon}
      <Slottable>{children}</Slottable>
      {ripples}
    </Comp>
  );
});

function PendingDots() {
  return (
    <span aria-hidden className="inline-flex items-center gap-0.5">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="size-1 rounded-full bg-current opacity-80 animate-[bar-breathe_900ms_ease-in-out_infinite]"
          style={{ animationDelay: `${i * 140}ms` }}
        />
      ))}
    </span>
  );
}

/** Icon-only button: `label` is both its accessible name and the tooltip that names the action. */
export function IconButton({
  label,
  className,
  children,
  tooltipSide = "top",
  ...rest
}: ButtonProps & { label: string; tooltipSide?: "top" | "right" | "bottom" | "left" }) {
  return (
    <Tooltip content={label} side={tooltipSide}>
      <Button variant="ghost" aria-label={label} className={cn("size-9 px-0", className)} {...rest}>
        {children}
      </Button>
    </Tooltip>
  );
}
