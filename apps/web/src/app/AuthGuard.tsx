import { useEffect } from "react";
import { Navigate, Outlet, useLocation } from "react-router";
import { isApiError } from "../api/errors";
import { useMe } from "../api/queries";
import { FullPageLoader } from "../components";
import { endSession, useSignedIn } from "../api/session";
import { AUTH_PAGES, loginPathFor } from "../lib/paths";
import { useIdleSignOut } from "./useIdleSignOut";

/**
 * Protects every app route (T040). Signed-out visitors go to `/login?next=<where they were>`;
 * sign-in returns them there. Expired tokens refresh silently inside the API client; when the
 * refresh fails the session clears and this guard redirects on the next render.
 *
 * A stored session is confirmed once with /me before the shell renders, behind the full-page logo
 * loader, so a dead session goes straight to sign-in instead of flashing the app. If /me rejects
 * the session (401, or 403 for any reason other than an unverified email) the stored tokens are
 * dropped so nothing keeps polling with them; an unverified account goes to the verify page.
 */
export function AuthGuard() {
  const signedIn = useSignedIn();
  useIdleSignOut(signedIn);
  const location = useLocation();
  const me = useMe();
  const rejected = me.isError && isApiError(me.error) && (me.error.status === 401 || me.error.status === 403);
  const unverified = rejected && isApiError(me.error) && me.error.code === "email_unverified";

  useEffect(() => {
    if (rejected && !unverified) {
      endSession();
    }
  }, [rejected, unverified]);

  if (!signedIn) return <Navigate to={loginPathFor(location)} replace />;
  if (unverified) return <Navigate to={AUTH_PAGES.verifyEmail} replace />;
  if (rejected) return <FullPageLoader label="Signing you out" />;
  if (me.isPending) return <FullPageLoader label="Checking your session" />;
  return <Outlet />;
}
