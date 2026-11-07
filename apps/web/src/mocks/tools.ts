/**
 * Mock API for spec 005 (tool library and knowledge bases), built from
 * specs/005-tools-knowledge/contracts/*.yaml. In-memory; documents become ready one poll after
 * upload. Used by Vitest and `pnpm dev:mock`.
 */
import { http } from "msw";
import type { KbDocument, KnowledgeBase } from "../api/knowledge";
import type { Tool, ToolDraft, ToolPreset } from "../api/tools";
import { json, page, problem, url } from "./http";

let seq = 0;
const ulid = (prefix: string) => `${prefix}_01J${String(++seq).padStart(23, "0")}`;
const now = () => new Date().toISOString();

export const toolStore: { tools: Tool[]; kbs: KnowledgeBase[]; docs: KbDocument[] } = { tools: [], kbs: [], docs: [] };

export function resetToolStore() {
  toolStore.tools = [];
  toolStore.kbs = [];
  toolStore.docs = [];
}

export function seedTool(draft: ToolDraft, usage = 0): Tool {
  const tool: Tool = {
    id: ulid("tool"),
    ...draft,
    mock_response: draft.mock_response ?? null,
    usage_count: usage,
    created_at: now(),
    updated_at: now(),
  };
  toolStore.tools.unshift(tool);
  return tool;
}

export function seedKb(name: string, docs: { name: string; status: KbDocument["status"] }[] = []): KnowledgeBase {
  const kb: KnowledgeBase = {
    id: ulid("kb"),
    name,
    description: "",
    status: "empty",
    attachable: false,
    document_count: 0,
    ready_count: 0,
    processing_count: 0,
    failed_count: 0,
    total_bytes: 0,
    agent_count: 0,
    created_at: now(),
    updated_at: now(),
  };
  toolStore.kbs.unshift(kb);
  for (const d of docs) {
    toolStore.docs.unshift({
      id: ulid("doc"),
      kb_id: kb.id,
      file_name: d.name,
      display_name: d.name,
      file_type: d.name.endsWith(".docx") ? "docx" : "pdf",
      file_size: 120_000,
      sha256: "0".repeat(64),
      status: d.status,
      created_at: now(),
    });
  }
  return derive(kb);
}

function derive(kb: KnowledgeBase): KnowledgeBase {
  const docs = toolStore.docs.filter((d) => d.kb_id === kb.id);
  const ready = docs.filter((d) => d.status === "ready").length;
  const processing = docs.filter((d) => d.status === "uploaded" || d.status === "processing").length;
  const failed = docs.filter((d) => d.status === "failed").length;
  const status = docs.length === 0 ? "empty" : processing ? "processing" : failed && ready ? "partial" : failed ? "failed" : "ready";
  return Object.assign(kb, {
    document_count: docs.length,
    ready_count: ready,
    processing_count: processing,
    failed_count: failed,
    total_bytes: docs.reduce((n, d) => n + d.file_size, 0),
    status,
    attachable: ready > 0,
  });
}

const PRESETS: ToolPreset[] = [
  {
    preset_id: "end_call_polite",
    type: "end_call",
    title: "End the call",
    summary: "Says a short goodbye, then hangs up.",
    tool: { type: "end_call", name: "end_call", description: "End the call when the caller is done", config: { message: "Goodbye!" } },
  },
];

export const toolHandlers = [
  http.get(url("/tools/presets"), () => json({ items: PRESETS })),
  http.get(url("/tools"), ({ request }) => {
    const search = new URL(request.url).searchParams.get("search")?.toLowerCase() ?? "";
    const items = toolStore.tools.filter((t) => !search || t.name.includes(search) || t.description.toLowerCase().includes(search));
    return json(page(items, request));
  }),
  http.post(url("/tools"), async ({ request }) => {
    const body = (await request.json()) as ToolDraft;
    if (!/^[a-z][a-z0-9_]{0,63}$/.test(body.name)) {
      return problem(422, "validation_failed", "Request is not valid", {
        errors: [{ pointer: "/name", code: "invalid_format", message: "Bad name" }],
      });
    }
    return json(seedTool(body), 201);
  }),
  http.get(url("/tools/:id"), ({ params }) => {
    const tool = toolStore.tools.find((t) => t.id === params.id);
    return tool ? json(tool) : problem(404, "not_found", "Not found");
  }),
  http.patch(url("/tools/:id"), async ({ params, request }) => {
    const tool = toolStore.tools.find((t) => t.id === params.id);
    if (!tool) return problem(404, "not_found", "Not found");
    Object.assign(tool, (await request.json()) as Partial<Tool>, { updated_at: now() });
    return json(tool);
  }),
  http.get(url("/knowledge-bases"), ({ request }) => json(page(toolStore.kbs.map(derive), request))),
  http.post(url("/knowledge-bases"), async ({ request }) => {
    const body = (await request.json()) as { name: string; description?: string };
    const kb = seedKb(body.name);
    kb.description = body.description ?? "";
    return json(kb, 201);
  }),
  http.get(url("/knowledge-bases/:id"), ({ params }) => {
    const kb = toolStore.kbs.find((k) => k.id === params.id);
    return kb ? json(derive(kb)) : problem(404, "not_found", "Not found");
  }),
  http.get(url("/knowledge-bases/:id/documents"), ({ params, request }) =>
    json(
      page(
        toolStore.docs.filter((d) => d.kb_id === params.id),
        request,
      ),
    ),
  ),
];
