import { LayoutDashboard, LogIn, Menu, UserPlus } from "lucide-react";
import { useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router";
import { useSignedIn } from "../../app/auth";
import { Button, Drawer, IconButton, Logo, PageTransition, cn, focusRing } from "../../components";

const navLink = ({ isActive }: { isActive: boolean }) =>
  cn("link-underline rounded-inline px-1 py-1 text-[14px] transition-colors", isActive ? "text-fg" : "text-fg-2 hover:text-fg", focusRing);

const SITE = [
  { to: "/pricing", label: "Pricing" },
  { to: "/enterprise", label: "Enterprise" },
];

/** Marketing chrome (FR-016): one-line nav, footer with legal links. Same tokens as the app. */
export function PublicLayout() {
  const signedIn = useSignedIn();
  const { pathname } = useLocation();
  const [open, setOpen] = useState(false);
  return (
    <div className="flex min-h-dvh flex-col bg-bg">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[70] focus:rounded-control focus:bg-surface focus:px-3 focus:py-2 focus:shadow-pop"
      >
        Skip to content
      </a>
      <header className="sticky top-0 z-30 border-b border-line bg-bg/80 backdrop-blur-md">
        <div className="mx-auto flex h-16 max-w-[1200px] items-center gap-8 px-4 sm:px-6">
          <Link to="/" className={cn("rounded-[9px]", focusRing)} aria-label="Callwright home">
            <Logo />
          </Link>
          <nav aria-label="Site" className="hidden items-center gap-6 sm:flex">
            {SITE.map((s) => (
              <NavLink key={s.to} to={s.to} className={navLink}>
                {s.label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-2">
            {signedIn ? (
              <Button asChild variant="primary" icon={<LayoutDashboard aria-hidden />}>
                <Link to="/dashboard">Open dashboard</Link>
              </Button>
            ) : (
              <>
                <Button asChild variant="ghost" className="hidden sm:inline-flex">
                  <Link to="/login">Sign in</Link>
                </Button>
                <Button asChild variant="primary" icon={<UserPlus aria-hidden />}>
                  <Link to="/register">Create account</Link>
                </Button>
              </>
            )}
            <IconButton label="Open menu" className="sm:hidden" onClick={() => setOpen(true)}>
              <Menu className="size-5" aria-hidden />
            </IconButton>
          </div>
        </div>
      </header>
      <Drawer open={open} onOpenChange={setOpen} title="Menu" width="md">
        <nav aria-label="Site menu" className="flex flex-col gap-1">
          {[...SITE, ...(signedIn ? [] : [{ to: "/login", label: "Sign in" }])].map((s) => (
            <Link
              key={s.to}
              to={s.to}
              onClick={() => setOpen(false)}
              className={cn("flex h-11 items-center gap-2 rounded-control px-3 text-[15px] text-fg hover:bg-surface-3", focusRing)}
            >
              {s.to === "/login" && <LogIn className="size-4 text-fg-3" aria-hidden />}
              {s.label}
            </Link>
          ))}
        </nav>
      </Drawer>
      <main id="main" className="flex-1">
        <PageTransition key={pathname}>
          <Outlet />
        </PageTransition>
      </main>
      <footer className="border-t border-line">
        <div className="mx-auto flex max-w-[1200px] flex-col gap-8 px-4 py-12 sm:flex-row sm:items-start sm:justify-between sm:px-6">
          <div className="flex flex-col gap-3">
            <Logo />
            <p className="max-w-[40ch] text-[13px] leading-relaxed text-fg-3">
              Build voice agents, put them on the phone, and fix what callers trip over.
            </p>
          </div>
          <nav aria-label="Footer" className="grid grid-cols-2 gap-x-14 gap-y-2.5 text-[13.5px] sm:grid-cols-3">
            {[
              ["/pricing", "Pricing"],
              ["/enterprise", "Enterprise"],
              ["/login", "Sign in"],
              ["/privacy", "Privacy"],
              ["/terms", "Terms"],
            ].map(([to, label]) => (
              <Link key={to} to={to!} className={cn("link-underline justify-self-start text-fg-2 hover:text-fg", focusRing)}>
                {label}
              </Link>
            ))}
          </nav>
        </div>
      </footer>
    </div>
  );
}
