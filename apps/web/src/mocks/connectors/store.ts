/**
 * In-memory state for the 022 mocks: Google connections, a small Drive folder tree, knowledge
 * sources and their sync runs. Sign-in in mock mode returns straight to the callback page.
 */
import type { Connection } from "../../api/connections";

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
} = {
  connections: [],
  states: new Set(),
  folders: [],
  sharedDrives: [],
  decline: false,
  scopes: ["openid", "email", DRIVE, SHEETS],
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
