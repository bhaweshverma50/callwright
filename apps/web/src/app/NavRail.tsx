import { SidebarSimple } from "@phosphor-icons/react";
import { NavLink } from "react-router";
import { Kbd, Logo, Tooltip, cn, focusRing } from "../components";
import { BILLING_ITEM, NAV, type NavItem } from "./nav";

/**
 * Collapsible navigation rail (T042, T096, FR-005). Collapsed to icons by default with label
 * tooltips; expanded it shows section headers. The choice is remembered per browser by Shell.
 */
export function NavRail({ expanded, onToggle }: { expanded: boolean; onToggle: () => void }) {
  return (
    <nav
      aria-label="Main"
      className={cn(
        "sticky top-0 flex h-dvh shrink-0 flex-col border-r border-line bg-rail transition-[width] duration-200 ease-out",
        expanded ? "w-[216px]" : "w-[56px]",
      )}
    >
      <div className={cn("flex h-12 items-center border-b border-line", expanded ? "px-3.5" : "justify-center")}>
        <NavLink to="/dashboard" className={cn("rounded-[7px]", focusRing)} aria-label="Callwright dashboard">
          <Logo compact={!expanded} />
        </NavLink>
      </div>

      <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto overflow-x-hidden px-2 py-3">
        {NAV.map((group, gi) => (
          <div key={group.label ?? gi} className="flex flex-col gap-0.5">
            {group.label &&
              (expanded ? (
                <p className="px-2 pb-1 font-mono text-[10.5px] uppercase tracking-[0.08em] text-fg-3">{group.label}</p>
              ) : (
                gi > 0 && <div role="separator" className="mx-2 mb-1 h-px bg-line" />
              ))}
            <ul className="flex flex-col gap-0.5">
              {group.items.map((item) => (
                <li key={item.to}>
                  <RailLink item={item} expanded={expanded} group={group.label} />
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      <div className="flex flex-col gap-0.5 border-t border-line px-2 py-2">
        <RailLink item={BILLING_ITEM} expanded={expanded} group={null} />
        <Tooltip
          side="right"
          content={
            <span className="flex items-center gap-2">
              {expanded ? "Collapse" : "Expand"} navigation <Kbd>[</Kbd>
            </span>
          }
        >
          <button
            type="button"
            onClick={onToggle}
            aria-expanded={expanded}
            aria-label={expanded ? "Collapse navigation" : "Expand navigation"}
            className={cn(
              "flex h-8 items-center gap-2.5 rounded-control px-2 text-[13px] text-fg-3 transition-colors hover:bg-surface-3 hover:text-fg",
              !expanded && "justify-center",
              focusRing,
            )}
          >
            <SidebarSimple className="size-[18px] shrink-0" aria-hidden />
            {expanded && <span>Collapse</span>}
          </button>
        </Tooltip>
      </div>
    </nav>
  );
}

function RailLink({ item, expanded, group }: { item: NavItem; expanded: boolean; group: string | null }) {
  const Icon = item.icon;
  return (
    <Tooltip content={group && group !== "Build" ? `${group}: ${item.label}` : item.label} side="right" enabled={!expanded}>
      <NavLink
        to={item.to}
        aria-label={expanded ? undefined : item.label}
        className={({ isActive }) =>
          cn(
            "group relative flex h-8 items-center gap-2.5 rounded-control px-2 text-[13px] transition-colors",
            !expanded && "justify-center",
            isActive ? "bg-surface text-fg shadow-panel" : "text-fg-2 hover:bg-surface-3 hover:text-fg",
            focusRing,
          )
        }
      >
        {({ isActive }) => (
          <>
            {isActive && <span aria-hidden className="absolute -left-2 top-1.5 h-5 w-[3px] rounded-r-full bg-accent" />}
            <Icon weight={isActive ? "fill" : "regular"} className={cn("size-[18px] shrink-0", isActive && "text-accent-text")} aria-hidden />
            {expanded && <span className="truncate">{item.label}</span>}
          </>
        )}
      </NavLink>
    </Tooltip>
  );
}
