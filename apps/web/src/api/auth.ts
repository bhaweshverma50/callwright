import { api, unwrap } from "./client";
import { endSession } from "./session";

/** Exchanges email and password for a session (the caller starts it with startSession). */
export function signIn(email: string, password: string) {
  return unwrap(api.POST("/auth/sign-in", { body: { email, password } }));
}

export function register(email: string, password: string, captchaToken?: string) {
  return unwrap(api.POST("/auth/register", { body: { email, password, ...(captchaToken ? { captcha_token: captchaToken } : {}) } }));
}

/** Public sign-in options; `google_signin` says whether "Continue with Google" is on. */
export function getAuthConfig() {
  return unwrap(api.GET("/auth/config"));
}

/** The Google URL to send the browser to; the caller keeps `state` to check on the way back. */
export function startGoogleSignIn() {
  return unwrap(api.POST("/auth/google/start"));
}

export function completeGoogleSignIn(code: string, state: string) {
  return unwrap(api.POST("/auth/google/complete", { body: { code, state } }));
}

export function resendVerification(email: string) {
  return unwrap(api.POST("/auth/verify-email/resend", { body: { email } }));
}

export function verifyEmail(tokenHash: string) {
  return unwrap(api.POST("/auth/verify-email", { body: { token_hash: tokenHash } }));
}

export function requestPasswordReset(email: string) {
  return unwrap(api.POST("/auth/password-reset", { body: { email } }));
}

export function confirmPasswordReset(tokenHash: string, newPassword: string) {
  return unwrap(api.POST("/auth/password-reset/confirm", { body: { token_hash: tokenHash, new_password: newPassword } }));
}

/**
 * Global sign-out (US1.3): revoke on the server, then end the session everywhere. The local part
 * runs even when the network call fails, which is logged rather than shown.
 */
export async function signOut() {
  try {
    await api.POST("/auth/sign-out");
  } catch (e) {
    console.warn("Sign-out did not reach the server; signing out on this device only.", e);
  }
  endSession();
}
