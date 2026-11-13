/**
 * In-memory state for the 022 mocks: Google connections, a small Drive folder tree, knowledge
 * sources and their sync runs. Sign-in in mock mode returns straight to the callback page.
 */
import type { Connection } from "../../api/connections";
import type { KnowledgeSource, SyncRunDetail } from "../../api/knowledge";

let seq = 0;
export const ulid = (prefix: string) => `${prefix}_01J${String(++seq).padStart(23, "0")}`;
export const now = () => new Date().toISOString();

export const DRIVE = "https://www.googleapis.com/auth/drive.readonly";
export const SHEETS = "https://www.googleapis.com/auth/spreadsheets";

export interface MockFolder {
  id: string;
  name: string;
  parent: string;
  drive_id: string | null;
}

export const connectorStore: {
  connections: Connection[];
  states: Set<string>;
  folders: MockFolder[];
  sharedDrives: { id: string; name: string }[];
  decline: boolean;
  scopes: string[];
  sources: KnowledgeSource[];
  runs: SyncRunDetail[];
} = {
  connections: [],
  states: new Set(),
  folders: [],
  sharedDrives: [],
  decline: false,
  scopes: ["openid", "email", DRIVE, SHEETS],
  sources: [],
  runs: [],
};

function seedFolders() {
  connectorStore.folders = [
    { id: "fld_clinic", name: "Clinic policies", parent: "root", drive_id: null },
    { id: "fld_2026", name: "2026", parent: "fld_clinic", drive_id: null },
    { id: "fld_listings", name: "Listings", parent: "root", drive_id: null },
    { id: "fld_team_hr", name: "HR", parent: "drv_team", drive_id: "drv_team" },
  ];
  connectorStore.sharedDrives = [{ id: "drv_team", name: "Team drive" }];
}

export function resetConnectorStore() {
  connectorStore.connections = [];
  connectorStore.states = new Set();
  connectorStore.decline = false;
  connectorStore.scopes = ["openid", "email", DRIVE, SHEETS];
  connectorStore.sources = [];
  connectorStore.runs = [];
  seedFolders();
}

export function seedConnection(over: Partial<Connection> = {}): Connection {
  const conn: Connection = {
    id: ulid("conn"),
    provider: "google",
    kind: "oauth",
    account_email: "drive.owner@example.com",
    scopes: ["openid", "email", DRIVE, SHEETS],
    sheets_access: true,
    health: "healthy",
    health_reason: null,
    last_success_at: now(),
    last_checked_at: now(),
    source_count: 0,
    created_at: now(),
    ...over,
  };
  connectorStore.connections.push(conn);
  return conn;
}

resetConnectorStore();

export function makeRun(sourceId: string, trigger: SyncRunDetail["trigger"], counts: Partial<SyncRunDetail["counts"]> = {}): SyncRunDetail {
  const run: SyncRunDetail = {
    id: ulid("ksr"),
    source_id: sourceId,
    trigger,
    status: "succeeded",
    failure_reason: null,
    started_at: now(),
    finished_at: now(),
    counts: { added: 0, updated: 0, unchanged: 0, renamed: 0, archived: 0, held_back: 0, skipped: 0, failed: 0, ...counts },
    errors: [],
    errors_truncated: 0,
  };
  connectorStore.runs.unshift(run);
  return run;
}

export function seedSource(kbId: string, over: Partial<KnowledgeSource> = {}): KnowledgeSource {
  const conn = connectorStore.connections[0] ?? seedConnection();
  const src: KnowledgeSource = {
    id: ulid("ksrc"),
    kb_id: kbId,
    connection_id: conn.id,
    account_email: conn.account_email,
    kind: "google_drive",
    root_kind: "folder",
    root_id: "fld_clinic",
    root_name: "Clinic policies",
    include_subfolders: true,
    interval_minutes: 15,
    state: "healthy",
    attention_reason: null,
    attention_message: null,
    held_archive: null,
    document_count: 0,
    last_success_at: now(),
    next_sync_at: now(),
    last_run: null,
    created_at: now(),
    ...over,
  };
  src.last_run = makeRun(src.id, "first", { added: src.document_count });
  connectorStore.sources.push(src);
  return src;
}
