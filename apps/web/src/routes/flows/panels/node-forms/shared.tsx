import type { ReactNode } from "react";
import type { ValidationIssue } from "../../../../api/flows";

export type FormProps<C> = {
  config: C;
  onChange: (next: C) => void;
  /** Server issues for this node, by field (`max_rounds`, `request.url`). */
  issues: ValidationIssue[];
  allowHttp?: boolean;
};

export function issueFor(issues: ValidationIssue[], field: string): string | null {
  const hit = issues.find((i) => i.field === field || (i.field ?? "").startsWith(`${field}.`));
  return hit ? hit.message : null;
}

/** A titled group inside a node panel, separated by a hairline. */
export function Group({
  title,
  description,
  icon,
  aside,
  children,
}: {
  title: ReactNode;
  description?: ReactNode;
  icon?: ReactNode;
  aside?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="flex flex-col gap-4 border-t border-line px-5 py-6 first:border-t-0">
      <header className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-2">
          {icon && <span className="mt-0.5 text-fg-3 [&_svg]:size-4">{icon}</span>}
          <div className="min-w-0">
            <h3 className="text-[14px] font-semibold leading-snug text-fg">{title}</h3>
            {description && <p className="mt-1 text-[13px] leading-relaxed text-fg-3">{description}</p>}
          </div>
        </div>
        {aside}
      </header>
      {children}
    </section>
  );
}
