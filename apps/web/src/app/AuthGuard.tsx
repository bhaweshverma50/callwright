import { Navigate, Outlet, useLocation } from "react-router";
import { loginPathFor, useSignedIn } from "./auth";

/**
 * Protects every app route (T040). Signed-out visitors go to `/login?next=<where they were>`;
 * sign-in returns them there. Expired tokens refresh silently inside the API client; when the
 * refresh fails the session clears and this guard redirects on the next render.
 */
export function AuthGuard() {
  const signedIn = useSignedIn();
  const location = useLocation();
  if (!signedIn) return <Navigate to={loginPathFor(location)} replace />;
  return <Outlet />;
}
