/**
 * The mock API's seeded account and the email-link tokens it issues. No imports, so the
 * Playwright helpers (tests/e2e) can read it as well as the unit tests, the mock database and the
 * mock-mode hints on the sign-in pages.
 */
export const DEMO_EMAIL = "ops@halcyon-dental.com";
export const DEMO_PASSWORD = "correct-horse-9";

/** The token in the verification link the mock API "emails" to `email`. */
export const mockVerifyToken = (email: string) => `verify-${email}`;

/** The token in the password reset link the mock API "emails" to `email`. */
export const mockResetToken = (email: string) => `reset-${email}`;
