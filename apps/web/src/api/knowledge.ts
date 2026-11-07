/**
 * Types and TanStack Query hooks for knowledge bases (spec 005, contracts/knowledge.yaml).
 * Uploads use XMLHttpRequest so the dialog can show upload progress.
 */
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api, apiUrl, fetchAll, readJson, sendAuthorized, unwrap } from "./client";
import type { components } from "./schema";
import type { ResponseOf } from "./types";
import { operationExtensions, schemaLimits } from "../lib/contract.gen";
import { isApiError } from "./errors";

type S = components["schemas"];

export type KnowledgeBase = S["KnowledgeBase"];
export type KbDocument = S["Document"];
export type DocumentStatus = S["DocumentStatus"];
export type SearchResponse = S["SearchResponse"];
export type SearchResult = S["SearchResult"];
export type DuplicateCheck = ResponseOf<"/knowledge-bases/{kb_id}/documents/check-duplicate", "post">;
export type DuplicateVerdict = DuplicateCheck["verdict"];
export type DuplicateMatch = DuplicateCheck["matches"][number];

export const MAX_FILE_BYTES = operationExtensions["POST /knowledge-bases/{kb_id}/documents"]["x-max-file-bytes"];
export const MAX_FILE_MB = MAX_FILE_BYTES / (1024 * 1024);
export const MAX_KBS_PER_AGENT = schemaLimits.AgentConfig.kb_ids.maxItems;
export const ACCEPT = ".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document";

export const kbKeys = {
  all: ["knowledge"] as const,
  list: (search: string, page: number) => ["knowledge", "list", search, page] as const,
  attachable: ["knowledge", "all-for-picker"] as const,
  detail: (id: string) => ["knowledge", "detail", id] as const,
  documents: (id: string, page: number) => ["knowledge", "documents", id, page] as const,
};

export function useKnowledgeBases(search: string, page = 1, pageSize = 24) {
  return useQuery({
    queryKey: kbKeys.list(search, page),
    queryFn: () => unwrap(api.GET("/knowledge-bases", { params: { query: { search: search || undefined, page, page_size: pageSize } } })),
    placeholderData: keepPreviousData,
    refetchInterval: (q) => (q.state.data?.items.some((k) => k.status === "processing") ? 3000 : false),
  });
}

/** Every knowledge base (the picker groups them into ready and not ready). */
export function useAllKnowledgeBases(enabled = true) {
  return useQuery({
    queryKey: kbKeys.attachable,
    queryFn: () => fetchAll((query) => unwrap(api.GET("/knowledge-bases", { params: { query } }))),
    enabled,
  });
}

export function useKnowledgeBase(id: string | undefined) {
  return useQuery({
    queryKey: kbKeys.detail(id ?? ""),
    queryFn: () => unwrap(api.GET("/knowledge-bases/{kb_id}", { params: { path: { kb_id: id! } } })),
    enabled: Boolean(id),
    refetchInterval: (q) => (q.state.data?.status === "processing" ? 3000 : false),
  });
}

export function useDocuments(id: string | undefined, page = 1) {
  return useQuery({
    queryKey: kbKeys.documents(id ?? "", page),
    queryFn: () => unwrap(api.GET("/knowledge-bases/{kb_id}/documents", { params: { path: { kb_id: id! }, query: { page, page_size: 50 } } })),
    enabled: Boolean(id),
    placeholderData: keepPreviousData,
    // Poll while anything is still being processed (status column updates live).
    refetchInterval: (q) => (q.state.data?.items.some((d) => d.status === "uploaded" || d.status === "processing") ? 2500 : false),
  });
}

export async function sha256Hex(file: Blob): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

export async function checkDuplicate(kbId: string, file: File, sha256: string) {
  return unwrap(
    api.POST("/knowledge-bases/{kb_id}/documents/check-duplicate", {
      params: { path: { kb_id: kbId } },
      body: { file_name: file.name, sha256, file_size: file.size },
    }),
  );
}

export interface UploadOptions {
  displayName?: string;
  replaceDocId?: string;
  acknowledgeDuplicate?: boolean;
  onProgress?: (fraction: number) => void;
  signal?: AbortSignal;
}

/** XHR runs one attempt and hands back a Response, so auth, refresh and the wake gate apply as usual. */
function xhrSend(url: string, form: FormData, token: string | null, opts: UploadOptions): Promise<Response> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    if (token) xhr.setRequestHeader("authorization", `Bearer ${token}`);
    xhr.upload.onprogress = (e) => e.lengthComputable && opts.onProgress?.(e.loaded / e.total);
    xhr.onload = () => resolve(new Response(xhr.responseText, { status: xhr.status, headers: { "content-type": "application/json" } }));
    xhr.onerror = () => reject(new TypeError("network"));
    xhr.onabort = () => reject(new TypeError("aborted"));
    opts.signal?.addEventListener("abort", () => xhr.abort());
    xhr.send(form);
  });
}

/** Multipart upload with progress (fetch has no upload progress). */
export async function uploadDocument(kbId: string, file: File, opts: UploadOptions = {}): Promise<KbDocument> {
  const form = new FormData();
  form.append("file", file, file.name);
  if (opts.displayName?.trim()) form.append("display_name", opts.displayName.trim());
  if (opts.replaceDocId) form.append("replace_doc_id", opts.replaceDocId);
  if (opts.acknowledgeDuplicate) form.append("acknowledge_duplicate", "true");
  const url = apiUrl("/knowledge-bases/{kb_id}/documents", { kb_id: kbId });
  return readJson(await sendAuthorized((token) => xhrSend(url, form, token, opts), url));
}

export async function documentUrl(kbId: string, docId: string): Promise<string> {
  const res = await unwrap(api.GET("/knowledge-bases/{kb_id}/documents/{doc_id}/url", { params: { path: { kb_id: kbId, doc_id: docId } } }));
  return res.url;
}

export async function deleteDocument(kbId: string, docId: string) {
  await unwrap(api.DELETE("/knowledge-bases/{kb_id}/documents/{doc_id}", { params: { path: { kb_id: kbId, doc_id: docId } } }));
}

export function reprocessDocument(kbId: string, docId: string) {
  return unwrap(api.POST("/knowledge-bases/{kb_id}/documents/{doc_id}/reprocess", { params: { path: { kb_id: kbId, doc_id: docId } } }));
}

/** An agent using a knowledge base, as the 409 `kb_in_use` lists them. */
export interface KbUser {
  agent_id: string;
  agent_name: string;
}

/**
 * Deletes a knowledge base. Without `confirm`, a base attached to agents answers 409 with the agents
 * using it (read them with kbUsersOf).
 */
export async function deleteKnowledgeBase(kbId: string, confirm: boolean) {
  await unwrap(api.DELETE("/knowledge-bases/{kb_id}", { params: { path: { kb_id: kbId }, query: { confirm } } }));
}

/**
 * The agents a 409 from deleteKnowledgeBase lists, or null for any other error. The contract does
 * not declare this field yet (the API sends it), so its shape is checked here.
 */
export function kbUsersOf(err: unknown): KbUser[] | null {
  if (!isApiError(err) || err.status !== 409) return null;
  const agents = err.problem.agents;
  return Array.isArray(agents) ? agents.filter((a): a is KbUser => typeof a?.agent_id === "string" && typeof a?.agent_name === "string") : [];
}

export function saveKnowledgeBase(existingId: string | null, body: { name: string; description: string }) {
  return unwrap(
    existingId ? api.PATCH("/knowledge-bases/{kb_id}", { params: { path: { kb_id: existingId } }, body }) : api.POST("/knowledge-bases", { body }),
  );
}

export function searchKnowledgeBase(kbId: string, query: string) {
  return unwrap(api.POST("/knowledge-bases/{kb_id}/search", { params: { path: { kb_id: kbId } }, body: { query, top_k: 4 } }));
}
