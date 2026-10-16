import { useCallback, useEffect, useState } from "react";
import { Outlet, useLocation } from "react-router";
import { Drawer, PageTransition, cn } from "../components";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";

const RAIL_KEY = "cw.rail.expanded";

/** Expanded unless this browser chose the icon rail before. */
function readExpanded(): boolean {
  try {
    return localStorage.getItem(RAIL_KEY) !== "0";
  } catch {
    return true;
  }
}

function isTyping(target: EventTarget | null) {
  const el = target as HTMLElement | null;
  return !!el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName));
}

/**
 * App shell (T042): the grouped sidebar, the top bar with workspace, balance and user menu, and
 * the routed page with a short route transition. Only identity and balance are read here;
 * feature credentials are never requested from the shell (FR-020, enforced by ESLint).
 */
export function Shell() {
  const [expanded, setExpanded] = useState(readExpanded);
  const [mobileOpen, setMobileOpen] = useState(false);
  const { pathname } = useLocation();

  const toggle = useCallback(() => {
    setExpanded((v) => {
      const next = !v;
      try {
        localStorage.setItem(RAIL_KEY, next ? "1" : "0");
      } catch {
        /* not remembered when storage is blocked */
      }
      return next;
    });
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "[" && !e.metaKey && !e.ctrlKey && !e.altKey && !isTyping(e.target)) {
        e.preventDefault();
        toggle();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [toggle]);

  return (
    <div className="flex min-h-dvh bg-bg">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[70] focus:rounded-control focus:bg-surface focus:px-3 focus:py-2 focus:shadow-pop"
      >
        Skip to content
      </a>
      <div
        className={cn(
          "hidden shrink-0 border-r border-line bg-sidebar transition-[width] duration-200 ease-out lg:block",
          expanded ? "w-[248px]" : "w-[72px]",
        )}
      >
        <div className="sticky top-0 h-dvh">
          <Sidebar expanded={expanded} onToggle={toggle} />
        </div>
      </div>
      <Drawer open={mobileOpen} onOpenChange={setMobileOpen} title="Callwright" side="left" width="md">
        <div className="-mx-5 -my-4 h-full">
          <Sidebar expanded inDrawer onNavigate={() => setMobileOpen(false)} />
        </div>
      </Drawer>
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar onOpenNav={() => setMobileOpen(true)} />
        <main id="main" tabIndex={-1} className="flex-1 px-4 pb-16 pt-6 outline-none sm:px-6 lg:px-10 lg:pt-8">
          <PageTransition key={pathname} className="mx-auto w-full max-w-[1320px]">
            <Outlet />
          </PageTransition>
        </main>
      </div>
    </div>
  );
}
