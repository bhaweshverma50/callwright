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

/**
 * Rows inside a Panel (bodyClassName="p-0"): one anatomy for settings, facts and forms. Every row
 * has the same 20px side padding and 16px vertical rhythm, a hairline between rows, an icon and
 * label on the left and the value or control on the right.
 */
export function PanelRows({ children, as: As = "div", className }: { children: ReactNode; as?: "div" | "dl"; className?: string }) {
  return <As className={cn("@container divide-y divide-line", className)}>{children}</As>;
}

const rowLabel = "flex min-w-0 items-start gap-3";
const rowIcon = "mt-[1px] shrink-0 text-fg-3 [&_svg]:size-4";

/** A form row: label and one-line help on the left, the control on the right (stacked when narrow). */
export function FieldRow({
  icon,
  label,
  htmlFor,
  description,
  descriptionId,
  inline = false,
  children,
}: {
  icon?: ReactNode;
  label: ReactNode;
  htmlFor: string;
  description?: ReactNode;
  descriptionId?: string;
  /** Small controls (switches) stay on the right at every width. */
  inline?: boolean;
  children: ReactNode;
}) {
  if (inline) {
    return (
      <div className="flex items-start justify-between gap-6 px-5 py-4">
        <div className={rowLabel}>
          {icon && <span className={rowIcon}>{icon}</span>}
          <div className="flex min-w-0 flex-col gap-0.5">
            <label htmlFor={htmlFor} className="cursor-pointer text-[13.5px] font-medium text-fg">
              {label}
            </label>
            {description && (
              <p id={descriptionId} className="text-[12.5px] leading-relaxed text-fg-3">
                {description}
              </p>
            )}
          </div>
        </div>
        <div className="shrink-0">{children}</div>
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-3 px-5 py-4 @[34rem]:flex-row @[34rem]:items-start @[34rem]:justify-between @[34rem]:gap-8">
      <div className={rowLabel}>
        {icon && <span className={rowIcon}>{icon}</span>}
        <div className="flex min-w-0 flex-col gap-0.5">
          <label htmlFor={htmlFor} className="cursor-pointer text-[13.5px] font-medium text-fg">
            {label}
          </label>
          {description && (
            <p id={descriptionId} className="text-[12.5px] leading-relaxed text-fg-3">
              {description}
            </p>
          )}
        </div>
      </div>
      <div className="flex min-w-0 flex-col items-stretch gap-1.5 pl-7 @[34rem]:w-[min(340px,52%)] @[34rem]:shrink-0 @[34rem]:items-end @[34rem]:pl-0">
        {children}
      </div>
    </div>
  );
}

/** A read-only fact row (inside `<PanelRows as="dl">`): label left, value right on one line. Long values truncate with a tooltip. */
export function InfoRow({ icon, label, children, title }: { icon?: ReactNode; label: ReactNode; children: ReactNode; title?: string }) {
  return (
    <div className="flex items-center justify-between gap-4 px-5 py-4">
      <dt className={cn(rowLabel, "items-center")}>
        {icon && <span className={cn(rowIcon, "mt-0")}>{icon}</span>}
        <span className="whitespace-nowrap text-[13.5px] font-medium text-fg">{label}</span>
      </dt>
      <dd title={title} className="min-w-0 truncate text-right text-[13.5px] text-fg-2">
        {children}
      </dd>
    </div>
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
