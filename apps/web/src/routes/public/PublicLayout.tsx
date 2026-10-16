import { Link, NavLink, Outlet } from "react-router";
import { useSignedIn } from "../../app/auth";
import { Button, Logo, cn, focusRing } from "../../components";

const navLink = ({ isActive }: { isActive: boolean }) =>
  cn("rounded-control px-2.5 py-1.5 text-[13.5px] transition-colors", isActive ? "text-fg" : "text-fg-2 hover:text-fg", focusRing);

/** Marketing chrome (FR-016): one-line nav, footer with legal links. Same tokens as the app. */
export function PublicLayout() {
  const signedIn = useSignedIn();
  return (
    <div className="flex min-h-dvh flex-col bg-bg">
      <header className="sticky top-0 z-30 border-b border-line bg-bg/85 backdrop-blur-sm">
        <div className="mx-auto flex h-14 max-w-[1200px] items-center gap-6 px-4 sm:px-6">
          <Link to="/" className={cn("rounded-[7px]", focusRing)} aria-label="Callwright home">
            <Logo />
          </Link>
          <nav aria-label="Site" className="hidden items-center gap-1 sm:flex">
            <NavLink to="/pricing" className={navLink}>
              Pricing
            </NavLink>
            <NavLink to="/enterprise" className={navLink}>
              Enterprise
            </NavLink>
          </nav>
          <div className="ml-auto flex items-center gap-2">
            {signedIn ? (
              <Button asChild variant="primary">
                <Link to="/dashboard">Open dashboard</Link>
              </Button>
            ) : (
              <>
                <Button asChild variant="ghost">
                  <Link to="/login">Sign in</Link>
                </Button>
                <Button asChild variant="primary">
                  <Link to="/register">Create account</Link>
                </Button>
              </>
            )}
          </div>
        </div>
      </header>
      <main id="main" className="flex-1">
        <Outlet />
      </main>
      <footer className="border-t border-line">
        <div className="mx-auto flex max-w-[1200px] flex-col gap-6 px-4 py-10 sm:flex-row sm:items-start sm:justify-between sm:px-6">
          <div className="flex flex-col gap-2">
            <Logo />
            <p className="max-w-[40ch] text-[12.5px] text-fg-3">Build voice agents, put them on the phone, and fix what callers trip over.</p>
          </div>
          <nav aria-label="Footer" className="grid grid-cols-2 gap-x-12 gap-y-2 text-[13px] sm:grid-cols-3">
            <Link to="/pricing" className="text-fg-2 hover:text-fg">
              Pricing
            </Link>
            <Link to="/enterprise" className="text-fg-2 hover:text-fg">
              Enterprise
            </Link>
            <Link to="/login" className="text-fg-2 hover:text-fg">
              Sign in
            </Link>
            <Link to="/privacy" className="text-fg-2 hover:text-fg">
              Privacy
            </Link>
            <Link to="/terms" className="text-fg-2 hover:text-fg">
              Terms
            </Link>
          </nav>
        </div>
      </footer>
    </div>
  );
}
