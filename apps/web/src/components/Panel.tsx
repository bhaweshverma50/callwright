import { createContext, useContext, type ReactNode } from "react";
import { cn } from "./cn";
import { InfoTip, TruncatedText } from "./TruncatedText";

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
              {description && <p className="text-[13px] text-fg-3">{description}</p>}
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

interface FieldRowIds {
  htmlFor: string;
  labelId: string;
  descriptionId?: string;
}

const FieldRowContext = createContext<FieldRowIds | null>(null);

/** Join space-separated id lists, dropping empties (`undefined` when nothing is left). */
export function joinIds(...ids: (string | undefined | null | false)[]): string | undefined {
  const out = [...new Set(ids.flatMap((i) => (i ? i.split(/\s+/) : [])).filter(Boolean))];
  return out.length ? out.join(" ") : undefined;
}

/**
 * The label and description ids of the FieldRow whose control has this `id`, so primitives that a
 * `<label for>` cannot name (slider thumbs) still get a name, and every control hears the row's
 * one-line help as its description. Empty outside a FieldRow or for other controls in the row.
 */
export function useFieldRowAria(id: string | undefined): { labelledBy?: string; describedBy?: string } {
  const row = useContext(FieldRowContext);
  if (!row || !id || row.htmlFor !== id) return {};
  return { labelledBy: row.labelId, describedBy: row.descriptionId };
}

/** A form row: label and one-line help on the left, the control on the right (stacked when narrow). */
export function FieldRow({
  icon,
  label,
  htmlFor,
  description,
  descriptionId,
  inline = false,
  hint,
  children,
}: {
  icon?: ReactNode;
  label: ReactNode;
  htmlFor: string;
  description?: ReactNode;
  descriptionId?: string;
  /** Small controls (switches) stay on the right at every width. */
  inline?: boolean;
  /** Extra detail behind an info tip after the label; the description stays the visible essentials. */
  hint?: ReactNode;
  children: ReactNode;
}) {
  const labelId = `${htmlFor}-label`;
  const descId = description ? (descriptionId ?? `${htmlFor}-desc`) : undefined;
  const ids: FieldRowIds = { htmlFor, labelId, descriptionId: descId };
  const labelEl = (
    <span className="flex items-center gap-1.5">
      <label id={labelId} htmlFor={htmlFor} className="cursor-pointer text-[14px] font-medium text-fg">
        {label}
      </label>
      {hint && <InfoTip label={`About ${typeof label === "string" ? label.toLowerCase() : "this setting"}`}>{hint}</InfoTip>}
    </span>
  );
  if (inline) {
    return (
      <FieldRowContext.Provider value={ids}>
        <div className="flex items-start justify-between gap-6 px-5 py-4">
          <div className={rowLabel}>
            {icon && <span className={rowIcon}>{icon}</span>}
            <div className="flex min-w-0 flex-col gap-0.5">
              {labelEl}
              {description && (
                <p id={descId} className="text-[13px] leading-relaxed text-fg-3">
                  {description}
                </p>
              )}
            </div>
          </div>
          <div className="shrink-0">{children}</div>
        </div>
      </FieldRowContext.Provider>
    );
  }
  return (
    <FieldRowContext.Provider value={ids}>
      <div className="flex flex-col gap-3 px-5 py-4 @[34rem]:flex-row @[34rem]:items-start @[34rem]:justify-between @[34rem]:gap-8">
        <div className={rowLabel}>
          {icon && <span className={rowIcon}>{icon}</span>}
          <div className="flex min-w-0 flex-col gap-0.5">
            {labelEl}
            {description && (
              <p id={descId} className="text-[13px] leading-relaxed text-fg-3">
                {description}
              </p>
            )}
          </div>
        </div>
        <div className="flex min-w-0 flex-col items-stretch gap-1.5 pl-7 @[34rem]:w-[min(340px,52%)] @[34rem]:shrink-0 @[34rem]:items-end @[34rem]:pl-0">
          {children}
        </div>
      </div>
    </FieldRowContext.Provider>
  );
}

/**
 * A read-only fact row (inside `<PanelRows as="dl">`): label left, value right on one line. Long
 * values end in an ellipsis and show in full in a tooltip; `title` gives the tooltip text when the
 * value is not plain text. `hint` adds an info tip after the label for terms that need explaining.
 */
export function InfoRow({
  icon,
  label,
  children,
  title,
  hint,
}: {
  icon?: ReactNode;
  label: ReactNode;
  children: ReactNode;
  title?: string;
  hint?: ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-4 px-5 py-4">
      <dt className={cn(rowLabel, "items-center")}>
        {icon && <span className={cn(rowIcon, "mt-0")}>{icon}</span>}
        <span className="flex items-center gap-1.5 whitespace-nowrap text-[14px] font-medium text-fg">
          {label}
          {hint && <InfoTip label={`About ${typeof label === "string" ? label.toLowerCase() : "this value"}`}>{hint}</InfoTip>}
        </span>
      </dt>
      <dd className="flex min-w-0 justify-end text-right text-[14px] text-fg-2">
        <TruncatedText title={title}>{children}</TruncatedText>
      </dd>
    </div>
  );
}

/** Page header: Unbounded title, one line on what the page is for, the primary action on the right. */
export function PageHeader({ title, description, actions }: { title: ReactNode; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-7 flex flex-wrap items-end justify-between gap-x-6 gap-y-4">
      <div className="flex min-w-0 flex-col gap-1.5">
        <h1 className="font-display text-[22px] leading-tight tracking-[-0.02em] text-fg sm:text-[26px]">{title}</h1>
        {description && <p className="max-w-[72ch] text-[14px] text-fg-2">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

/** Caption for figures and key/value keys: sentence case, small, muted. */
export function Label({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={cn("text-[13px] text-fg-3", className)}>{children}</span>;
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
