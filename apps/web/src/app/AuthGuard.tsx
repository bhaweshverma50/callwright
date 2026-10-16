import { Navigate, Outlet, useLocation } from "react-router";
import { useMe } from "../api/queries";
import { FullPageLoader } from "../components";
import { loginPathFor, useSignedIn } from "./auth";

/**
 * Protects every app route (T040). Signed-out visitors go to `/login?next=<where they were>`;
 * sign-in returns them there. Expired tokens refresh silently inside the API client; when the
 * refresh fails the session clears and this guard redirects on the next render.
 *
 * A stored session is confirmed once with /me before the shell renders, behind the full-page logo
 * loader, so a dead session goes straight to sign-in instead of flashing the app. Later visits use
 * the cached identity and render at once; if /me fails for another reason the pages show the error.
 */
export function AuthGuard() {
  const signedIn = useSignedIn();
  const location = useLocation();
  const me = useMe();
  if (!signedIn) return <Navigate to={loginPathFor(location)} replace />;
  if (me.isPending) return <FullPageLoader label="Checking your session" />;
  return <Outlet />;
}
