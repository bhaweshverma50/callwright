import { Slot, Slottable } from "@radix-ui/react-slot";
import { forwardRef, type AnimationEvent, type ButtonHTMLAttributes, type FocusEvent, type PointerEvent, type ReactNode } from "react";
import { cn, focusRing } from "./cn";
import { useRipple } from "./motion";

type Variant = "primary" | "secondary" | "ghost" | "danger" | "link";
type Size = "sm" | "md" | "lg";

const variants: Record<Variant, string> = {
  primary: cn(
    "grad-action sheen text-white shadow-[0_1px_0_rgb(255_255_255/0.18)_inset,0_6px_16px_-8px_rgb(51_70_232/0.7)]",
    "hover:shadow-[0_1px_0_rgb(255_255_255/0.18)_inset,0_10px_22px_-8px_rgb(91_60_244/0.75)] hover:brightness-[1.06]",
    "disabled:bg-none disabled:bg-surface-3 disabled:text-fg-3 disabled:shadow-none disabled:brightness-100",
  ),
  secondary:
    "bg-surface text-fg border border-line-strong hover:border-accent/60 hover:bg-accent-soft/40 disabled:text-fg-3 disabled:border-line disabled:bg-surface",
  ghost: "text-fg-2 hover:text-fg hover:bg-surface-3 disabled:text-fg-3 disabled:bg-transparent",
  danger: "bg-danger-solid text-white hover:brightness-110 disabled:bg-surface-3 disabled:text-fg-3",
  link: "link-underline text-accent-text px-0 h-auto rounded-inline",
};

const sizes: Record<Size, string> = {
  sm: "h-8 px-3 text-[12.5px] gap-1.5 [&_svg]:size-3.5",
  md: "h-9 px-3.5 text-[13px] gap-2 [&_svg]:size-4",
  lg: "h-11 px-5 text-[14px] gap-2 [&_svg]:size-[18px]",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  /** Shows a pending indicator and blocks clicks; keeps the label for screen readers. */
  pending?: boolean;
  /** Icon before the label. */
  icon?: ReactNode;
  asChild?: boolean;
  /** The single hero CTA only: one sheen pass every 7 s while idle. */
  idleSheen?: boolean;
}

/** Starts one sheen pass unless one is running; the pass clears itself on animationend. */
function startSheen(el: HTMLElement) {
  if (!el.classList.contains("sheen") || el.dataset.sheen !== undefined) return;
  el.dataset.sheen = "";
}

/**
 * Buttons. Primary is the one cobalt to violet action per view: one sheen pass on hover or
 * keyboard focus (never restarted mid-pass), a quick press scale and a ripple. Labels name the action; no arrow glyph after the text.
 */
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant = "secondary",
    size = "md",
    pending = false,
    icon,
    asChild,
    idleSheen,
    className,
    children,
    disabled,
    onPointerDown,
    onPointerEnter,
    onFocus,
    onAnimationEnd,
    ...rest
  },
  ref,
) {
  const Comp = asChild ? Slot : "button";
  const { onPointerDown: ripple, ripples } = useRipple();
  return (
    <Comp
      ref={ref}
      className={cn(
        "relative inline-flex shrink-0 cursor-pointer select-none items-center justify-center overflow-hidden whitespace-nowrap rounded-control font-medium",
        "transition-[background-color,border-color,color,box-shadow,filter,transform] duration-150",
        "active:scale-[var(--press-scale)] active:duration-[var(--press-duration)]",
        "disabled:cursor-not-allowed disabled:active:scale-100",
        focusRing,
        variants[variant],
        variant === "primary" && idleSheen && "sheen-idle",
        variant !== "link" && sizes[size],
        className,
      )}
      disabled={asChild ? undefined : disabled || pending}
      aria-busy={pending || undefined}
      onPointerDown={(e: PointerEvent<HTMLButtonElement>) => {
        if (variant !== "link") ripple(e);
        onPointerDown?.(e);
      }}
      onPointerEnter={(e: PointerEvent<HTMLButtonElement>) => {
        startSheen(e.currentTarget);
        onPointerEnter?.(e);
      }}
      onFocus={(e: FocusEvent<HTMLButtonElement>) => {
        try {
          if (e.currentTarget.matches(":focus-visible")) startSheen(e.currentTarget);
        } catch {
          /* :focus-visible unsupported: no sheen on focus */
        }
        onFocus?.(e);
      }}
      onAnimationEnd={(e: AnimationEvent<HTMLButtonElement>) => {
        if (e.animationName === "sheen") delete e.currentTarget.dataset.sheen;
        onAnimationEnd?.(e);
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

export function IconButton({ label, className, children, ...rest }: ButtonProps & { label: string }) {
  return (
    <Button variant="ghost" aria-label={label} className={cn("size-9 px-0", className)} {...rest}>
      {children}
    </Button>
  );
}
