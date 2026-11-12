/**
 * Types and TanStack Query hooks for Google connections (spec 022, contracts/connectors.yaml).
 * Sign-in starts with `startGoogleConnection` (the browser then leaves for Google) and finishes on
 * the callback page with `completeGoogleConnection`.
 */
import { useQuery } from "@tanstack/react-query";
import { api, unwrap } from "./client";
import type { components } from "./schema";

type S = components["schemas"];

export type Connection = S["Connection"];
export type ConnectionDetail = S["ConnectionDetail"];
export type ConnectionUser = S["ConnectionUser"];
export type DriveFolder = S["DriveFolder"];

export const connectionKeys = {
  all: ["connections"] as const,
  list: ["connections", "list"] as const,
  detail: (id: string) => ["connections", "detail", id] as const,
  folders: (id: string, parent: string, driveId: string | null) => ["connections", "folders", id, parent, driveId] as const,
  sharedDrives: (id: string) => ["connections", "shared-drives", id] as const,
};

export function useConnections() {
  return useQuery({
    queryKey: connectionKeys.list,
    queryFn: () => unwrap(api.GET("/connections")),
  });
}

export function useConnection(id: string | undefined) {
  return useQuery({
    queryKey: connectionKeys.detail(id ?? ""),
    queryFn: () => unwrap(api.GET("/connections/{connection_id}", { params: { path: { connection_id: id! } } })),
    enabled: Boolean(id),
  });
}

/** Where the browser goes to sign in with Google (or, to reconnect, the same flow for one connection). */
export function startGoogleConnection(connectionId?: string) {
  return unwrap(api.POST("/connections/google/start", { body: connectionId ? { connection_id: connectionId } : {} }));
}

export function completeGoogleConnection(body: { state: string; code?: string; error?: string }) {
  return unwrap(api.POST("/connections/google/complete", { body }));
}

export function testConnection(id: string) {
  return unwrap(api.POST("/connections/{connection_id}/test", { params: { path: { connection_id: id } } }));
}

export async function deleteConnection(id: string): Promise<void> {
  await unwrap(api.DELETE("/connections/{connection_id}", { params: { path: { connection_id: id } } }));
}

export const SCOPE_LABELS: Record<string, string> = {
  "https://www.googleapis.com/auth/drive.readonly": "Drive (read-only)",
  "https://www.googleapis.com/auth/spreadsheets": "Sheets",
};

/** Session key holding where the user started sign-in, so the callback can send them back there. */
export const CONNECT_RETURN_KEY = "cw.connect.return";
