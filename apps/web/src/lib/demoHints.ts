/**
 * Mock-mode hints for the public auth pages: the seeded account and the email-link tokens the
 * mock API issues. main.tsx installs them when it starts the mock API, so production pages never
 * import mocks; without them (a real API) the pages show no hints.
 */
export interface DemoHints {
  email: string;
  password: string;
  /** The token in the verification link the mock API "emails" to `email`. */
  verifyToken: (email: string) => string;
  /** The token in the password reset link the mock API "emails" to `email`. */
  resetToken: (email: string) => string;
}

let installed: DemoHints | null = null;

export function installDemoHints(hints: DemoHints | null) {
  installed = hints;
}

export function demoHints(): DemoHints | null {
  return installed;
}
