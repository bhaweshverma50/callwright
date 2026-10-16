// Shared-demo gate on Vercel: HTTP Basic auth from BASIC_AUTH_USER / BASIC_AUTH_PASSWORD.
// With either variable unset the site is open (local preview, or a deliberately public demo).
export const config = { matcher: "/(.*)" };

export default function middleware(request: Request): Response | undefined {
  const user = process.env.BASIC_AUTH_USER;
  const pass = process.env.BASIC_AUTH_PASSWORD;
  if (!user || !pass) return undefined;
  const header = request.headers.get("authorization") ?? "";
  const [scheme, encoded] = header.split(" ");
  if (scheme === "Basic" && encoded) {
    const [u, ...rest] = atob(encoded).split(":");
    if (u === user && rest.join(":") === pass) return undefined;
  }
  return new Response("Sign in to view the Callwright demo.", {
    status: 401,
    headers: { "WWW-Authenticate": 'Basic realm="Callwright demo", charset="UTF-8"' },
  });
}
