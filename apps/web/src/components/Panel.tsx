import type { ReactNode } from "react";
import { cn } from "./cn";

/**
 * Work surface (12px radius, 1px line, light shadow) for a group of related content. Use it only
 * when the grouping carries meaning; page sections otherwise sit on the paper.
 */
export function Panel({
  title,
  description,
  icon,
  actions,
  children,
  className,
  bodyClassName,
  as: As = "section",
}: {
  title?: ReactNode;
  description?: ReactNode;
  icon?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
  as?: "section" | "div";
}) {
  return (
    <As className={cn("rounded-panel border border-line bg-surface shadow-1", className)}>
      {(title || actions) && (
        <header className="flex items-start justify-between gap-4 border-b border-line px-5 py-3.5">
          <div className="flex items-start gap-2.5">
            {icon && <span className="mt-0.5 text-fg-3 [&_svg]:size-4">{icon}</span>}
            <div className="flex flex-col gap-0.5">
              {title && <h2 className="text-[14px] font-semibold text-fg">{title}</h2>}
              {description && <p className="text-[12.5px] text-fg-3">{description}</p>}
            </div>
          </div>
          {actions && <div className="flex items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={cn(bodyClassName ?? "p-5")}>{children}</div>
    </As>
  );
}

/** Page header: Unbounded title, one line on what the page is for, the primary action on the right. */
export function PageHeader({ title, description, actions }: { title: ReactNode; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-7 flex flex-wrap items-end justify-between gap-x-6 gap-y-4">
      <div className="flex min-w-0 flex-col gap-1.5">
        <h1 className="font-display text-[22px] font-medium leading-tight tracking-[-0.02em] text-fg sm:text-[26px]">{title}</h1>
        {description && <p className="max-w-[72ch] text-[13.5px] text-fg-2">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

/** Caption for figures and key/value keys: sentence case, small, muted. */
export function Label({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={cn("text-[12.5px] text-fg-3", className)}>{children}</span>;
}

/**
 * Main column plus a right-hand inspector pane (docs/DESIGN.md section 5). At 1280px and up the
 * inspector is a sticky column; below that it stacks after the main column.
 */
export function WorkLayout({ main, inspector, className }: { main: ReactNode; inspector: ReactNode; className?: string }) {
  return (
    <div className={cn("grid grid-cols-[minmax(0,1fr)] items-start gap-6", inspector ? "xl:grid-cols-[minmax(0,1fr)_360px]" : undefined, className)}>
      <div className="min-w-0">{main}</div>
      {inspector ? (
        <aside aria-label="Inspector" className="flex min-w-0 flex-col gap-4 xl:sticky xl:top-[84px]">
          {inspector}
        </aside>
      ) : null}
    </div>
  );
}
