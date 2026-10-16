import { Slot } from "@radix-ui/react-slot";
import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { cn, focusRing } from "./cn";

type Variant = "primary" | "secondary" | "ghost" | "danger" | "link";
type Size = "sm" | "md" | "lg";

const variants: Record<Variant, string> = {
  primary:
    "bg-accent text-accent-fg hover:bg-accent-hover shadow-[inset_0_1px_0_rgb(255_255_255/0.12)] disabled:bg-surface-3 disabled:text-fg-3 disabled:shadow-none",
  secondary:
    "bg-surface text-fg border border-line-strong hover:bg-surface-2 hover:border-fg-3 disabled:text-fg-3 disabled:border-line disabled:bg-surface",
  ghost: "text-fg-2 hover:text-fg hover:bg-surface-3 disabled:text-fg-3 disabled:bg-transparent",
  danger: "bg-danger text-white hover:brightness-95 disabled:bg-surface-3 disabled:text-fg-3",
  link: "text-accent-text underline-offset-4 hover:underline px-0 h-auto",
};

const sizes: Record<Size, string> = {
  sm: "h-7 px-2.5 text-[12.5px] gap-1.5",
  md: "h-8 px-3 text-[13px] gap-2",
  lg: "h-10 px-4 text-sm gap-2",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  /** Shows a pending indicator and blocks clicks; keeps the label for screen readers. */
  pending?: boolean;
  /** Icon before the label. */
  icon?: ReactNode;
  asChild?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", pending = false, icon, asChild, className, children, disabled, ...rest },
  ref,
) {
  const Comp = asChild ? Slot : "button";
  return (
    <Comp
      ref={ref}
      className={cn(
        "inline-flex shrink-0 select-none items-center justify-center whitespace-nowrap rounded-control font-medium",
        "transition-[background-color,border-color,color,transform] duration-150 active:translate-y-px",
        "disabled:cursor-not-allowed disabled:active:translate-y-0",
        focusRing,
        variants[variant],
        variant !== "link" && sizes[size],
        className,
      )}
      disabled={asChild ? undefined : disabled || pending}
      aria-busy={pending || undefined}
      {...(asChild ? {} : { type: rest.type ?? "button" })}
      {...rest}
    >
      {asChild ? (
        children
      ) : (
        <>
          {pending ? <PendingDots /> : icon}
          {children}
        </>
      )}
    </Comp>
  );
});

function PendingDots() {
  return (
    <span aria-hidden className="inline-flex items-center gap-0.5">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="size-1 rounded-full bg-current animate-shimmer"
          style={{ animationDelay: `${i * 160}ms` }}
        />
      ))}
    </span>
  );
}

export function IconButton({
  label,
  className,
  children,
  ...rest
}: ButtonProps & { label: string }) {
  return (
    <Button variant="ghost" aria-label={label} title={label} className={cn("size-8 px-0", className)} {...rest}>
      {children}
    </Button>
  );
}
