import { api } from "./client";
import { endSession } from "./session";

/**
 * Global sign-out (US1.3): revoke on the server, then end the session everywhere. The local part
 * runs even when the network call fails.
 */
export async function signOut() {
  try {
    await api.POST("/auth/sign-out");
  } catch {
    /* offline: still sign out locally */
  }
  endSession();
}
