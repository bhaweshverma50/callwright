/**
 * How this browser last signed in, so the sign-in page can mark it "Last used". Kept on purpose
 * after sign-out (that is when it helps); it only names a method, never an account.
 */
export type SignInMethod = "email" | "google";

const KEY = "cw.lastSignIn";

export function rememberSignIn(method: SignInMethod) {
  try {
    localStorage.setItem(KEY, method);
  } catch {
    /* storage unavailable: no hint next time */
  }
}

export function lastSignIn(): SignInMethod | null {
  try {
    const v = localStorage.getItem(KEY);
    return v === "email" || v === "google" ? v : null;
  } catch {
    return null;
  }
}
