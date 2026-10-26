import type { ReactNode } from "react";

/** Panel header for the Tools and Knowledge tabs: actions wrap under the title on narrow screens. */
export function TabHeader({ icon, title, description, actions }: { icon: ReactNode; title: string; description: ReactNode; actions?: ReactNode }) {
  return (
    <header className="flex flex-wrap items-start justify-between gap-x-4 gap-y-3 border-b border-line px-5 py-3.5">
      <div className="flex min-w-[200px] flex-1 items-start gap-2.5">
        <span className="mt-0.5 text-fg-3 [&_svg]:size-4">{icon}</span>
        <div className="flex flex-col gap-0.5">
          <h2 className="text-[14px] font-semibold text-fg">{title}</h2>
          <p className="text-[12.5px] text-fg-3">{description}</p>
        </div>
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </header>
  );
}
