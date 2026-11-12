/**
 * Mock API for spec 022 connections (specs/022-knowledge-connectors/contracts/connectors.yaml).
 * Sign-in returns straight to the callback page with a fake code, like the API's fake Drive mode.
 * Knowledge source handlers are added with US2.
 */
import { http } from "msw";
import type { KnowledgeSource } from "../../api/knowledge";
import { json, page, problemDetail, url } from "../http";
import { DRIVE, SHEETS, connectorStore, makeRun, now, seedConnection, seedSource, ulid } from "./store";

const CALLBACK = "/settings/connections/callback";

function usersOf(id: string) {
  return connectorStore.sources
    .filter((s) => s.connection_id === id)
    .map((s) => ({ source_id: s.id, kb_id: s.kb_id, kb_name: s.root_name, root_name: s.root_name }));
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
    // Sign-in is a full page load, which resets this in-memory store in the browser (mock mode),
    // so a state in the mock's own format is accepted even when it is no longer remembered.
    if (!connectorStore.states.delete(body.state) && !body.state.startsWith("state_")) {
      return problemDetail(400, "oauth_state_invalid", "This sign-in link expired or belongs to someone else. Start again.");
    }
    if (body.error) return problemDetail(400, "oauth_declined", "Google access was not granted, so no connection was made.");
    if (!connectorStore.scopes.includes(DRIVE)) {
      return problemDetail(400, "oauth_scope_missing", "Read-only Google Drive access is required for knowledge sync.");
    }
    const existing = connectorStore.connections[0];
    if (existing) {
      Object.assign(existing, {
        health: "healthy",
        health_reason: null,
        scopes: connectorStore.scopes,
        sheets_access: connectorStore.scopes.includes(SHEETS),
        last_success_at: now(),
      });
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

// ---- Knowledge sources (022 US2 to US5) -------------------------------------------------------

const sourceOf = (id: unknown) => connectorStore.sources.find((s) => s.id === id);
const notFound = () => problemDetail(404, "not_found", "No knowledge source with that id exists in this workspace.");

export const sourceHandlers = [
  http.get(url("/connections/:id/drive/shared-drives"), () =>
    json({
      items: connectorStore.sharedDrives.map((d) => ({ id: d.id, name: d.name, kind: "shared_drive", drive_id: d.id })),
      next_page_token: null,
    }),
  ),
  http.get(url("/connections/:id/drive/folders"), ({ request }) => {
    const q = new URL(request.url).searchParams;
    const driveId = q.get("drive_id");
    const parent = q.get("parent") ?? "root";
    const start = driveId && parent === "root" ? driveId : parent;
    const items = connectorStore.folders
      .filter((f) => f.parent === start)
      .map((f) => ({ id: f.id, name: f.name, kind: "folder", drive_id: f.drive_id }));
    return json({ items, next_page_token: null });
  }),
  http.get(url("/knowledge-bases/:kbId/sources"), ({ params }) => json({ items: connectorStore.sources.filter((s) => s.kb_id === params.kbId) })),
  http.post(url("/knowledge-bases/:kbId/sources"), async ({ params, request }) => {
    const body = (await request.json()) as { root_id: string; root_kind: "folder" | "shared_drive"; include_subfolders?: boolean };
    if (connectorStore.sources.some((s) => s.kb_id === params.kbId && s.root_id === body.root_id)) {
      return problemDetail(409, "source_exists", "This folder is already a source of this knowledge base.");
    }
    const name =
      connectorStore.folders.find((f) => f.id === body.root_id)?.name ??
      connectorStore.sharedDrives.find((d) => d.id === body.root_id)?.name ??
      "Folder";
    const src = seedSource(String(params.kbId), {
      root_id: body.root_id,
      root_kind: body.root_kind,
      root_name: name,
      include_subfolders: body.include_subfolders ?? true,
      state: "pending",
    });
    return json(src, 201);
  }),
  http.get(url("/knowledge-bases/:kbId/sources/:id"), ({ params }) => {
    const src = sourceOf(params.id);
    return src ? json({ ...src, not_imported: [] }) : notFound();
  }),
  http.patch(url("/knowledge-bases/:kbId/sources/:id"), async ({ params, request }) => {
    const src = sourceOf(params.id);
    if (!src) return notFound();
    Object.assign(src, (await request.json()) as Partial<KnowledgeSource>);
    return json(src);
  }),
  http.delete(url("/knowledge-bases/:kbId/sources/:id"), ({ params }) => {
    if (!sourceOf(params.id)) return notFound();
    connectorStore.sources = connectorStore.sources.filter((s) => s.id !== params.id);
    return new Response(null, { status: 204 });
  }),
  http.post(url("/knowledge-bases/:kbId/sources/:id/sync"), ({ params }) => {
    const src = sourceOf(params.id);
    if (!src) return notFound();
    if (src.state === "syncing") return problemDetail(409, "sync_running", "A sync of this source is running.", { run: src.last_run });
    const run = makeRun(src.id, "manual", { unchanged: src.document_count });
    src.last_run = run;
    src.last_success_at = now();
    return json(run, 202);
  }),
  http.post(url("/knowledge-bases/:kbId/sources/:id/held-archive/:decision"), ({ params }) => {
    const src = sourceOf(params.id);
    if (!src) return notFound();
    if (!src.held_archive) return problemDetail(409, "nothing_held", "No archiving is waiting for a decision.");
    Object.assign(src, { held_archive: null, state: "healthy", attention_reason: null, attention_message: null });
    return json(src);
  }),
  http.get(url("/knowledge-bases/:kbId/sources/:id/runs"), ({ params, request }) =>
    json(
      page(
        connectorStore.runs.filter((r) => r.source_id === params.id),
        request,
      ),
    ),
  ),
  http.get(url("/knowledge-bases/:kbId/sources/:id/runs/:runId"), ({ params }) => {
    const run = connectorStore.runs.find((r) => r.id === params.runId);
    return run ? json(run) : notFound();
  }),
];
