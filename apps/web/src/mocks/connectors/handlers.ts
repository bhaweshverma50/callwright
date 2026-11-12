/**
 * Mock API for spec 022 connections (specs/022-knowledge-connectors/contracts/connectors.yaml).
 * Sign-in returns straight to the callback page with a fake code, like the API's fake Drive mode.
 * Knowledge source handlers are added with US2.
 */
import { http } from "msw";
import { json, problemDetail, url } from "../http";
import { DRIVE, SHEETS, connectorStore, now, seedConnection, ulid } from "./store";

const CALLBACK = "/settings/connections/callback";

function usersOf(_id: string) {
  return [] as { source_id: string; kb_id: string; kb_name: string; root_name: string }[];
}

export const connectorHandlers = [
  http.get(url("/connections"), () => json({ items: connectorStore.connections, google_configured: true })),
  http.post(url("/connections/google/start"), async () => {
    const state = ulid("state").toLowerCase().padEnd(24, "x");
    connectorStore.states.add(state);
    const outcome = connectorStore.decline ? "error=access_denied" : "code=fake-code";
    return json({ authorization_url: `${window.location.origin}${CALLBACK}?${outcome}&state=${state}`, expires_in_s: 600 });
  }),
  http.post(url("/connections/google/complete"), async ({ request }) => {
    const body = (await request.json()) as { state: string; code?: string; error?: string };
    if (!connectorStore.states.delete(body.state)) {
      return problemDetail(400, "oauth_state_invalid", "This sign-in link expired or belongs to someone else. Start again.");
    }
    if (body.error) return problemDetail(400, "oauth_declined", "Google access was not granted, so no connection was made.");
    if (!connectorStore.scopes.includes(DRIVE)) {
      return problemDetail(400, "oauth_scope_missing", "Read-only Google Drive access is required for knowledge sync.");
    }
    const existing = connectorStore.connections[0];
    if (existing) {
      Object.assign(existing, { health: "healthy", health_reason: null, scopes: connectorStore.scopes, sheets_access: connectorStore.scopes.includes(SHEETS), last_success_at: now() });
      return json(existing);
    }
    return json(seedConnection({ scopes: connectorStore.scopes, sheets_access: connectorStore.scopes.includes(SHEETS) }), 201);
  }),
  http.get(url("/connections/:id"), ({ params }) => {
    const conn = connectorStore.connections.find((c) => c.id === params.id);
    if (!conn) return problemDetail(404, "not_found", "No connection with that id exists in this workspace.");
    return json({ ...conn, users: usersOf(conn.id), activity: [] });
  }),
  http.post(url("/connections/:id/test"), ({ params }) => {
    const conn = connectorStore.connections.find((c) => c.id === params.id);
    if (!conn) return problemDetail(404, "not_found", "No connection with that id exists in this workspace.");
    conn.last_checked_at = now();
    return json(conn);
  }),
  http.delete(url("/connections/:id"), ({ params }) => {
    const conn = connectorStore.connections.find((c) => c.id === params.id);
    if (!conn) return problemDetail(404, "not_found", "No connection with that id exists in this workspace.");
    const users = usersOf(conn.id);
    if (users.length) return problemDetail(409, "connection_in_use", "Remove the knowledge sources that use this connection first.", { users });
    connectorStore.connections = connectorStore.connections.filter((c) => c.id !== conn.id);
    return new Response(null, { status: 204 });
  }),
];
