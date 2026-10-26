import type { ReactNode } from "react";
import { cn } from "../../../../components";

/** A titled group of fields inside the tool editor; groups are separated by a hairline. */
export function FormSection({
  title,
  description,
  icon,
  aside,
  children,
  className,
}: {
  title: ReactNode;
  description?: ReactNode;
  icon?: ReactNode;
  aside?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("flex flex-col gap-4 border-t border-line pt-5 first:border-t-0 first:pt-0", className)}>
      <header className="flex flex-wrap items-start justify-between gap-x-3 gap-y-2">
        <div className="flex min-w-[220px] flex-1 items-start gap-2.5">
          {icon && <span className="mt-0.5 text-fg-3 [&_svg]:size-4">{icon}</span>}
          <div className="flex flex-col gap-0.5">
            <h3 className="text-[14px] font-semibold text-fg">{title}</h3>
            {description && <p className="text-[12.5px] leading-relaxed text-fg-3">{description}</p>}
          </div>
        </div>
        {aside}
      </header>
      {children}
    </section>
  );
}
