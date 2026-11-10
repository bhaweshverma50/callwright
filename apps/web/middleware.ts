// Shared-demo gate on Vercel: HTTP Basic auth from BASIC_AUTH_USER / BASIC_AUTH_PASSWORD.
// With either variable unset the site is open (local preview, or a deliberately public demo).
export const config = { matcher: "/(.*)" };

const encoder = new TextEncoder();

// Compares SHA-256 digests with no early exit, so the time does not depend on where values differ.
async function sameSecret(given: string, expected: string): Promise<boolean> {
  const [a, b] = await Promise.all([given, expected].map(async (v) => new Uint8Array(await crypto.subtle.digest("SHA-256", encoder.encode(v)))));
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a[i] ^ b[i];
  return diff === 0;
}

function credentials(header: string): [string, string] | null {
  const [scheme, encoded] = header.split(" ");
  if (scheme !== "Basic" || !encoded) return null;
  try {
    const [user, ...rest] = atob(encoded).split(":");
    return [user, rest.join(":")];
  } catch {
    return null;
  }
}

export default async function middleware(request: Request): Promise<Response | undefined> {
  const user = process.env.BASIC_AUTH_USER;
  const pass = process.env.BASIC_AUTH_PASSWORD;
  if (!user || !pass) return undefined;
  const given = credentials(request.headers.get("authorization") ?? "");
  if (given) {
    const [userOk, passOk] = await Promise.all([sameSecret(given[0], user), sameSecret(given[1], pass)]);
    if (userOk && passOk) return undefined;
  }
  return new Response("Sign in to view the Callwright demo.", {
    status: 401,
    headers: { "WWW-Authenticate": 'Basic realm="Callwright demo", charset="UTF-8"' },
  });
}
