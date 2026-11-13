/** Runtime configuration from Vite env. Every value has a safe default. */
const raw = import.meta.env;

export const env = {
  apiBaseUrl: (raw.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "") || "http://localhost:8100/v1",
  mocks: raw.VITE_API_MOCKS === "true",
  /** Cloudflare Turnstile site key; unset means the register form has no captcha. */
  turnstileSiteKey: (raw.VITE_TURNSTILE_SITE_KEY as string | undefined) || undefined,
  salesContactUrl: (raw.VITE_SALES_CONTACT_URL as string | undefined) || "mailto:sales@callwright.dev",
} as const;
