import { Buildings } from "@phosphor-icons/react";
import { useCallback, useEffect, useState } from "react";
import { Outlet } from "react-router";
import { useMe } from "../api/queries";
import { Skeleton } from "../components";
import { BalanceChip } from "./BalanceChip";
import { NavRail } from "./NavRail";
import { UserMenu } from "./UserMenu";

const RAIL_KEY = "cw.rail.expanded";

function readExpanded(): boolean {
  try {
    return localStorage.getItem(RAIL_KEY) === "1";
  } catch {
    return false;
  }
}

function isTyping(target: EventTarget | null) {
  const el = target as HTMLElement | null;
  return !!el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName));
}

/**
 * App shell (T042): navigation rail, top bar with workspace, balance and user menu, and the
 * routed page. Only identity and balance are read here; feature credentials are never
 * requested from the shell (FR-020, enforced by ESLint).
 */
export function Shell() {
  const [expanded, setExpanded] = useState(readExpanded);
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
      <NavRail expanded={expanded} onToggle={toggle} />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar />
        <main id="main" tabIndex={-1} className="flex-1 px-6 pb-16 pt-7 outline-none lg:px-10">
          <div className="mx-auto w-full max-w-[1240px]">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}

function TopBar() {
  const { data: me, isPending } = useMe();
  return (
    <header className="sticky top-0 z-30 flex h-12 items-center justify-between gap-4 border-b border-line bg-bg/85 px-6 backdrop-blur-sm lg:px-10">
      <div className="flex min-w-0 items-center gap-2 text-[13px] text-fg-2">
        <Buildings className="size-4 shrink-0 text-fg-3" aria-hidden />
        {isPending ? <Skeleton className="h-3 w-36" /> : <span className="truncate font-medium text-fg">{me?.workspace.name}</span>}
      </div>
      <div className="flex items-center gap-3">
        <BalanceChip />
        <UserMenu />
      </div>
    </header>
  );
}
