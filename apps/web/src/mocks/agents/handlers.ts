/**
 * Mock API for spec 002 (agents, agent versions, templates, LLM and voice catalogs, ambient audio,
 * prompt assistant), built from specs/002-agent-builder/contracts/*.yaml. Status codes and problem
 * codes follow the contracts. Behaviour switches for manual testing:
 * - GET /voices/elevenlabs/voices?search=offline returns 503 catalog_unavailable (retry path)
 * - deleting an agent whose name contains "Billing" returns 409 agent_in_use with a phone number
 */
import { delay, http, HttpResponse } from "msw";
import type {
  AgentConfig,
  AgentPage,
  AgentSummary,
  AgentType,
  AmbientAudioFile,
  PromptAiResponse,
  SaveResult,
  TemplateCategory,
  TemplateSummary,
  VersionDetail,
  VersionPage,
} from "../../api/agents";
import { scanPlaceholders } from "../../lib/agentVariables";
import { appendTransaction, balanceOf, db, mockId, save } from "../db";
import { chimeDataUri } from "./audio";
import type { FlowGraph } from "../../api/flows";
import { seedMockFlow } from "../flows";
import { llmCatalog, voiceCatalog } from "./catalog";
import { diffConfigs } from "./diff";
import { defaultConfig, overlay, validateConfig } from "./rules";
import { insertAgent, saveDraft, store, toDetail, toSummary, toVersionSummary, versionById, workspaceUploadKeys, type MockAgent } from "./store";
import { CATEGORY_LABELS, TEMPLATES } from "./templates";
import { VOICES } from "./voices";
import { json, page, problem, unauthorized, url } from "../http";

function workspaceOf(request: Request): string | null {
  const token = request.headers.get("authorization")?.replace(/^Bearer\s+/i, "");
  if (!token || !token.startsWith("mock-access.")) return null;
  const id = db().sessions[token];
  return db().users.find((u) => u.id === id)?.workspace_id ?? null;
}

const notFound = (what = "Agent") => problem(404, "not_found", `${what} not found`);
const etagOf = (a: MockAgent) => ({ etag: `"${a.draft_revision}"` });

function findAgent(ws: string, id: string): MockAgent | undefined {
  return store().agents.find((a) => a.id === id && a.workspace_id === ws && !a.deleted_at);
}

function nameError(name: unknown) {
  if (typeof name !== "string" || !name.trim()) return { pointer: "/name", code: "required", message: "Give the agent a name." };
  if (name.trim().length > 80) return { pointer: "/name", code: "out_of_range", message: "Keep the name to 80 characters or fewer." };
  return null;
}

function templateTypeError(templateType: "single_prompt" | "flow") {
  const made = templateType === "flow" ? "a flow agent" : "a single-prompt agent";
  return { pointer: "/template_id", code: "invalid_format", message: `This template creates ${made}; create that type from it.` };
}

function failValidation(errors: { pointer: string; code: string; message: string }[]) {
  return problem(422, "validation_failed", "The configuration has problems", { errors });
}

/** The templates a list or count request selects: search, direction and type, plus the category for the list. */
function matchTemplates(q: URLSearchParams, withCategory: boolean) {
  const category = withCategory ? q.get("category") : null;
  const direction = q.get("direction");
  const agentType = q.get("agent_type");
  const search = (q.get("search") ?? "").trim().toLowerCase();
  return TEMPLATES.filter(
    (t) =>
      (!category || t.category === category) &&
      (!direction || t.direction === direction) &&
      (!agentType || t.agent_type === agentType) &&
      (!search || t.name.toLowerCase().includes(search) || t.description.toLowerCase().includes(search)),
  );
}

export const agentHandlers = [
  // catalogs
  http.get(url("/llms/catalog"), () => json(llmCatalog, 200, { "cache-control": "private, max-age=300" })),
  http.get(url("/voices/catalog"), () => json(voiceCatalog)),

  http.get(url("/voices/ambient-audio"), ({ request }) => {
    const ws = workspaceOf(request);
    if (!ws) return unauthorized();
    const items: AmbientAudioFile[] = store()
      .ambient.filter((a) => a.workspace_id === ws && !a.deleted_at)
      .map((a, i) => ({
        key: a.key,
        filename: a.filename,
        content_type: a.content_type,
        size_bytes: a.size_bytes,
        created_at: a.created_at,
        preview_url: chimeDataUri(11 + i),
      }));
    return json({ items });
  }),

  http.post(url("/voices/ambient-audio"), async ({ request }) => {
    const ws = workspaceOf(request);
    if (!ws) return unauthorized();
    const form = await request.formData();
    const file = form.get("file");
    if (!(file instanceof File)) return failValidation([{ pointer: "/file", code: "required", message: "Choose an audio file." }]);
    const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
    const types: Record<string, string> = {
      mp3: "audio/mpeg",
      wav: "audio/wav",
      ogg: "audio/ogg",
      flac: "audio/flac",
      aac: "audio/aac",
      opus: "audio/opus",
    };
    if (!types[ext]) return problem(415, "unsupported_media_type", "Not a supported audio format");
    if (file.size > 10 * 1024 * 1024) return problem(413, "file_too_large", "File larger than 10 MB");
    if (store().ambient.filter((a) => a.workspace_id === ws && !a.deleted_at).length >= 20)
      return problem(409, "upload_limit", "Workspace already has 20 uploads");
    await delay(500);
    const row = {
      workspace_id: ws,
      key: `workspaces/${ws}/ambient/${mockId("aud").slice(4)}.${ext}`,
      filename: file.name.slice(0, 200),
      content_type: types[ext]!,
      size_bytes: file.size,
      created_at: new Date().toISOString(),
      deleted_at: null,
    };
    store().ambient.push(row);
    save();
    const { workspace_id: _w, deleted_at: _d, ...rest } = row;
    return json<AmbientAudioFile>({ ...rest, preview_url: chimeDataUri(11) }, 201);
  }),

  http.delete(url("/voices/ambient-audio"), ({ request }) => {
    const ws = workspaceOf(request);
    if (!ws) return unauthorized();
    const key = new URL(request.url).searchParams.get("key");
    const row = store().ambient.find((a) => a.key === key && a.workspace_id === ws && !a.deleted_at);
    if (!row) return problem(404, "not_found", "Upload not found");
    const inUse = store().agents.some(
      (a) =>
        a.workspace_id === ws &&
        !a.deleted_at &&
        a.draft_config.advanced.background_audio.source?.kind === "upload" &&
        (a.draft_config.advanced.background_audio.source as { key: string }).key === key,
    );
    if (inUse) return problem(409, "audio_in_use", "An agent uses this sound");
    row.deleted_at = new Date().toISOString();
    save();
    return new HttpResponse(null, { status: 204 });
  }),

  http.get(url("/voices/:provider/voices"), async ({ params, request }) => {
    const provider = String(params.provider);
    const meta = voiceCatalog.tts.find((p) => p.provider === provider);
    if (!meta) return problem(404, "not_found", "Provider not in the catalog");
    const q = new URL(request.url).searchParams;
    const search = (q.get("search") ?? "").trim().toLowerCase();
    if (provider === "elevenlabs" && search === "offline") return problem(503, "catalog_unavailable", "Voice listing temporarily unavailable");
    const gender = q.get("gender");
    const language = q.get("language");
    const limit = Math.min(100, Math.max(1, Number(q.get("limit") ?? 50)));
    const cursor = Number(q.get("cursor") ?? 0);
    await delay(meta.voice_listing?.server_search ? 220 : 120);
    const all = (VOICES[provider] ?? []).filter(
      (v) =>
        (!search || v.name.toLowerCase().includes(search) || (v.description ?? "").toLowerCase().includes(search)) &&
        (!gender || v.gender === gender) &&
        (!language || v.languages.includes(language) || v.languages.includes(language.split("-")[0]!)),
    );
    const items = all.slice(cursor, cursor + limit);
    return json({ items, next_cursor: cursor + limit < all.length ? String(cursor + limit) : null });
  }),

  // templates
  http.get(url("/templates/categories"), ({ request }) => {
    // Counts follow the search, direction and type filters (not the category), as the API does.
    const counts = new Map<TemplateCategory, number>();
    for (const t of matchTemplates(new URL(request.url).searchParams, false)) counts.set(t.category, (counts.get(t.category) ?? 0) + 1);
    const items = (Object.keys(CATEGORY_LABELS) as TemplateCategory[])
      .filter((c) => counts.get(c))
      .map((id) => ({ id, label: CATEGORY_LABELS[id], count: counts.get(id)! }));
    return json({ items });
  }),
  http.get(url("/templates"), async ({ request }) => {
    await delay(120);
    const items: TemplateSummary[] = matchTemplates(new URL(request.url).searchParams, true).map(({ config: _c, ...rest }) => rest);
    return json({ items });
  }),
  http.get(url("/templates/:template_id"), ({ params }) => {
    const t = TEMPLATES.find((x) => x.id === params.template_id);
    return t ? json(t) : problem(404, "not_found", "Template not found");
  }),

  // agents
  http.get(url("/agents/defaults"), ({ request }) => {
    const q = new URL(request.url).searchParams;
    const type = (q.get("type") as AgentType | null) ?? "single_prompt";
    return json(defaultConfig(type, q.get("language") ?? "en-US"));
  }),

  http.post(url("/agents/validate"), async ({ request }) => {
    const ws = workspaceOf(request);
    if (!ws) return unauthorized();
    const body = (await request.json()) as { type: AgentType; config: unknown };
    await delay(40);
    return json(validateConfig(body.type ?? "single_prompt", body.config, { uploadKeys: workspaceUploadKeys(ws) }));
  }),

  http.get(url("/agents"), async ({ request }) => {
    const ws = workspaceOf(request);
    if (!ws) return unauthorized();
    const q = new URL(request.url).searchParams;
    const search = (q.get("search") ?? "").trim();
    const type = q.get("type");
    const status = q.get("status") as "live" | "draft" | "attention" | null;
    const sort = q.get("sort") ?? "updated";
    await delay(160);
    const matched = store()
      .agents.filter((a) => a.workspace_id === ws && !a.deleted_at && (!type || a.type === type))
      .filter((a) => !search || a.id === search || a.name.toLowerCase().includes(search.toLowerCase()))
      .map(toSummary);
    const is = {
      live: (a: AgentSummary) => a.published_version !== null,
      draft: (a: AgentSummary) => a.published_version === null,
      attention: (a: AgentSummary) => !!a.has_publish_blockers,
    };
    const rows = matched
      .filter((a) => !status || is[status](a))
      .sort((a, b) =>
        sort === "name"
          ? a.name.toLowerCase().localeCompare(b.name.toLowerCase())
          : sort === "created"
            ? b.created_at.localeCompare(a.created_at)
            : b.updated_at.localeCompare(a.updated_at),
      );
    return json<AgentPage>({
      counts: {
        all: matched.length,
        live: matched.filter(is.live).length,
        draft: matched.filter(is.draft).length,
        attention: matched.filter(is.attention).length,
      },
      ...page(rows, q),
    });
  }),

  http.post(url("/agents"), async ({ request }) => {
    const ws = workspaceOf(request);
    if (!ws) return unauthorized();
    const key = request.headers.get("idempotency-key");
    const s = store();
    const body = (await request.json()) as { name?: string; type?: AgentType; language?: string; template_id?: string; config?: unknown };
    // Check and insert with no await between them, so concurrent repeats of a key create one agent.
    if (key && s.idem[`${ws}:${key}`]) {
      const prior = findAgent(ws, s.idem[`${ws}:${key}`]!);
      if (prior) {
        await delay(300);
        return json(toDetail(prior), 201, etagOf(prior));
      }
    }
    const type = body.type ?? "single_prompt";
    let base = defaultConfig(type, body.language ?? (body.config as { language?: string } | undefined)?.language ?? "en-US");
    let note: string | null = null;
    if (body.template_id) {
      const t = TEMPLATES.find((x) => x.id === body.template_id);
      if (!t) return problem(404, "not_found", "Template not found");
      if (t.agent_type !== type) return failValidation([templateTypeError(t.agent_type)]);
      const { agent_name: _n, graph: _g, ...tpl } = t.config;
      base = overlay(defaultConfig(type, tpl.language), tpl) as AgentConfig;
      // The template names no voice: the language default for its provider applies (data-model 6).
      const provider = voiceCatalog.tts.find((p) => p.provider === base.tts.provider);
      base.tts.voice_id = provider?.default_voice_by_language?.[base.language] ?? base.tts.voice_id;
      note = `Created from ${t.name}`;
    }
    const config = overlay(base, body.config ?? {}) as AgentConfig;
    const result = validateConfig(type, config, { uploadKeys: workspaceUploadKeys(ws) });
    const errors = [...(nameError(body.name) ? [nameError(body.name)!] : []), ...result.errors];
    if (errors.length) return failValidation(errors);
    const agent = insertAgent(ws, body.name!.trim(), type, result.normalized_config, body.template_id ? "template" : "create", {
      template_id: body.template_id ?? null,
      note,
    });
    if (key) s.idem[`${ws}:${key}`] = agent.id;
    save();
    await delay(300);
    return json(toDetail(agent), 201, etagOf(agent));
  }),

  // A flow agent from a flow template. Without template_id this passes on to the flows mock.
  http.post(url("/flows"), async ({ request }) => {
    const ws = workspaceOf(request);
    if (!ws) return unauthorized();
    const body = (await request.json()) as { name?: string; language?: string; template_id?: string };
    if (!body.template_id) return undefined;
    const t = TEMPLATES.find((x) => x.id === body.template_id);
    if (!t) return problem(404, "not_found", "Template not found");
    if (t.agent_type !== "flow") return failValidation([templateTypeError(t.agent_type)]);
    if (nameError(body.name)) return failValidation([nameError(body.name)!]);
    const { agent_name: _n, graph, ...tpl } = t.config;
    const config = overlay(defaultConfig("flow", body.language ?? tpl.language), tpl) as AgentConfig;
    const agent = insertAgent(ws, body.name!.trim(), "flow", validateConfig("flow", config, { uploadKeys: workspaceUploadKeys(ws) }).normalized_config, "template", {
      template_id: t.id,
      note: `Created from ${t.name}`,
    });
    save();
    const flow = seedMockFlow(agent.id, agent.name, graph as unknown as FlowGraph);
    await delay(300);
    return json({ agent_id: agent.id, flow, warnings: [] }, 201, { ETag: `"${flow.revision}"` });
  }),

  http.get(url("/agents/:agent_id"), async ({ request, params }) => {
    const ws = workspaceOf(request);
    if (!ws) return unauthorized();
    const a = findAgent(ws, String(params.agent_id));
    await delay(120);
    return a ? json(toDetail(a), 200, etagOf(a)) : notFound();
  }),

  http.patch(url("/agents/:agent_id"), async ({ request, params }) => {
    const ws = workspaceOf(request);
    if (!ws) return unauthorized();
    const a = findAgent(ws, String(params.agent_id));
    if (!a) return notFound();
    const body = (await request.json()) as { name?: string };
    const e = nameError(body.name);
    if (e) return failValidation([e]);
    a.name = body.name!.trim();
    a.updated_at = new Date().toISOString();
    save();
    return json(toSummary(a));
  }),

  http.delete(url("/agents/:agent_id"), async ({ request, params }) => {
    const ws = workspaceOf(request);
    if (!ws) return unauthorized();
    const a = findAgent(ws, String(params.agent_id));
    if (!a) return notFound();
    await delay(250);
    if (/billing/i.test(a.name))
      return problem(409, "agent_in_use", "Agent is attached to a live channel", {
        attachments: [{ kind: "phone_number", id: "pn_01JB2M7Q8V3K5X9Z4R6T2W8Y0C", label: "+1 (415) 555-0142" }],
      });
    a.deleted_at = new Date().toISOString();
    save();
    return new HttpResponse(null, { status: 204 });
  }),

  http.put(url("/agents/:agent_id/draft"), async ({ request, params }) => {
    const ws = workspaceOf(request);
    if (!ws) return unauthorized();
    const a = findAgent(ws, String(params.agent_id));
    if (!a) return notFound();
    const match = request.headers.get("if-match")?.replace(/"/g, "");
    if (match !== String(a.draft_revision))
      return problem(412, "draft_changed", "The draft changed since it was loaded", { current_revision: a.draft_revision });
    const body = (await request.json()) as { name?: string; config: AgentConfig; note?: string };
    const result = validateConfig(a.type, body.config, { uploadKeys: workspaceUploadKeys(ws) });
    const errors = [...(body.name !== undefined && nameError(body.name) ? [nameError(body.name)!] : []), ...result.errors];
    if (body.note && body.note.length > 500)
      errors.push({ pointer: "/note", code: "out_of_range", message: "Keep the note to 500 characters or fewer." });
    if (errors.length) return failValidation(errors);
    await delay(320);
    const renamed = body.name !== undefined && body.name.trim() !== a.name;
    if (renamed) a.name = body.name!.trim();
    const { created, version } = saveDraft(a, result.normalized_config, "save", { note: body.note?.trim() || null });
    if (renamed && !created) a.draft_revision += 1;
    save();
    return json<SaveResult>(
      {
        agent: toDetail(a),
        created,
        version: { id: version.id, version_number: version.version_number, created_at: version.created_at },
        warnings: result.warnings,
        publish_blockers: result.publish_blockers,
      },
      200,
      etagOf(a),
    );
  }),

  http.post(url("/agents/:agent_id/duplicate"), async ({ request, params }) => {
    const ws = workspaceOf(request);
    if (!ws) return unauthorized();
    const s = store();
    const key = request.headers.get("idempotency-key");
    const body = ((await request.json().catch(() => ({}))) ?? {}) as { name?: string; version_id?: string };
    if (key && s.idem[`${ws}:${key}`]) {
      const prior = findAgent(ws, s.idem[`${ws}:${key}`]!);
      if (prior) {
        await delay(260);
        return json(toDetail(prior), 201, etagOf(prior));
      }
    }
    const a = findAgent(ws, String(params.agent_id));
    if (!a) return notFound();
    const from = body.version_id ? versionById(body.version_id) : null;
    if (body.version_id && from?.agent_id !== a.id) return notFound("Version");
    const name = (body.name ?? `${a.name} (copy)`).slice(0, 80);
    const copy = insertAgent(ws, name, a.type, structuredClone(from?.config ?? a.draft_config), "duplicate", { note: `Copied from ${a.name}` });
    if (key) s.idem[`${ws}:${key}`] = copy.id;
    save();
    await delay(260);
    return json(toDetail(copy), 201, etagOf(copy));
  }),

  // versions
  http.get(url("/agents/:agent_id/versions"), async ({ request, params }) => {
    const ws = workspaceOf(request);
    if (!ws) return unauthorized();
    const a = findAgent(ws, String(params.agent_id));
    if (!a) return notFound();
    const q = new URL(request.url).searchParams;
    const includeTest = q.get("include_test") === "true";
    await delay(140);
    const rows = store()
      .versions.filter((v) => v.agent_id === a.id && (includeTest || v.source !== "test"))
      .sort((x, y) => y.version_number - x.version_number);
    return json<VersionPage>(
      page(
        rows.map((v) => toVersionSummary(v, a)),
        q,
      ),
    );
  }),

  http.get(url("/agents/:agent_id/versions/:version_id"), ({ request, params }) => {
    const ws = workspaceOf(request);
    if (!ws) return unauthorized();
    const v = versionById(String(params.version_id));
    const a = store().agents.find((x) => x.id === params.agent_id && x.workspace_id === ws);
    if (!v || !a || v.agent_id !== a.id) return notFound("Version");
    return json<VersionDetail>({
      ...toVersionSummary(v, a),
      agent_id: a.id,
      schema_version: 1,
      config: v.config,
      publish_blockers: v.publish_blockers,
    });
  }),

  http.get(url("/agents/:agent_id/versions/:version_id/diff"), async ({ request, params }) => {
    const ws = workspaceOf(request);
    if (!ws) return unauthorized();
    const a = findAgent(ws, String(params.agent_id));
    const v = versionById(String(params.version_id));
    if (!a || !v || v.agent_id !== a.id) return notFound("Version");
    const against = new URL(request.url).searchParams.get("against") ?? "";
    const from = against === "draft" ? a.draft_config : versionById(against)?.config;
    if (!from) return notFound("Version");
    await delay(120);
    return json({ from: against, to: v.id, changes: diffConfigs(from, v.config) });
  }),

  http.post(url("/agents/:agent_id/versions/:version_id/restore"), async ({ request, params }) => {
    const ws = workspaceOf(request);
    if (!ws) return unauthorized();
    const a = findAgent(ws, String(params.agent_id));
    const v = versionById(String(params.version_id));
    if (!a || !v || v.agent_id !== a.id) return notFound("Version");
    const match = request.headers.get("if-match")?.replace(/"/g, "");
    if (match !== String(a.draft_revision))
      return problem(412, "draft_changed", "The draft changed since it was loaded", { current_revision: a.draft_revision });
    const body = ((await request.json().catch(() => ({}))) ?? {}) as { note?: string; publish?: boolean };
    const check = validateConfig(a.type, v.config, { uploadKeys: workspaceUploadKeys(ws) });
    if (body.publish && check.publish_blockers.length)
      return problem(422, "publish_blocked", "This version cannot be published", { errors: check.publish_blockers });
    await delay(300);
    const { version } = saveDraft(a, check.normalized_config, "restore", {
      note: body.note?.trim() || null,
      restoredFrom: v.id,
    });
    if (body.publish) a.pinned_version_id = version.id;
    save();
    return json<SaveResult>(
      {
        agent: toDetail(a),
        created: true,
        version: { id: version.id, version_number: version.version_number, created_at: version.created_at },
        warnings: check.warnings,
        publish_blockers: check.publish_blockers,
      },
      200,
      etagOf(a),
    );
  }),

  http.put(url("/agents/:agent_id/published-version"), async ({ request, params }) => {
    const ws = workspaceOf(request);
    if (!ws) return unauthorized();
    const a = findAgent(ws, String(params.agent_id));
    if (!a) return notFound();
    const { version_id } = (await request.json()) as { version_id: string };
    const v = versionById(version_id);
    if (!v || v.agent_id !== a.id) return notFound("Version");
    const blockers = validateConfig(a.type, v.config, { uploadKeys: workspaceUploadKeys(ws) }).publish_blockers;
    if (blockers.length) return problem(422, "publish_blocked", "This version cannot be published", { errors: blockers });
    await delay(260);
    a.pinned_version_id = v.id;
    a.updated_at = new Date().toISOString();
    save();
    return json(toSummary(a));
  }),

  http.delete(url("/agents/:agent_id/published-version"), async ({ request, params }) => {
    const ws = workspaceOf(request);
    if (!ws) return unauthorized();
    const a = findAgent(ws, String(params.agent_id));
    if (!a) return notFound();
    await delay(200);
    a.pinned_version_id = null;
    save();
    return new HttpResponse(null, { status: 204 });
  }),

  // prompt assistant (US6)
  http.post(url("/prompt-ai/generate"), async ({ request }) => {
    const ws = workspaceOf(request);
    if (!ws) return unauthorized();
    const s = store();
    const key = request.headers.get("idempotency-key");
    if (key && s.aiIdem[`${ws}:${key}`]) return json(s.aiIdem[`${ws}:${key}`]);
    if (balanceOf(db(), ws) <= 0n) return problem(402, "insufficient_credit", "Balance at or below zero");
    const now = Date.now();
    const recent = (s.aiCalls[ws] ?? []).filter((t) => now - t < 60_000);
    if (recent.length >= 20)
      return problem(429, "rate_limited", "Too many assistant requests", { retry_after_s: Math.ceil((recent[0]! + 60_000 - now) / 1000) });
    s.aiCalls[ws] = [...recent, now];
    const body = (await request.json()) as {
      messages: { role: string; content: string }[];
      current?: { prompt?: string; begin_message?: string | null } | null;
    };
    const ask = body.messages.filter((m) => m.role === "user").pop()?.content ?? "";
    await delay(1100);
    const res = draftPrompt(ask, body.current?.prompt ?? "", body.current?.begin_message ?? null);
    appendTransaction(db(), ws, "feature_charge", "-0.020000", "Prompt generation", now, { feature_key: "prompt_generation" });
    db().usage.push({ workspace_id: ws, feature_key: "prompt_generation", at: new Date(now).toISOString(), raw: "0.014000", billable: "0.020000" });
    if (key) s.aiIdem[`${ws}:${key}`] = res;
    save();
    return json(res);
  }),
];

/** Deterministic stand-in for the assistant model (quickstart PROMPT_AI_MODEL=fake). */
function draftPrompt(ask: string, current: string, greeting: string | null): PromptAiResponse {
  const lower = ask.toLowerCase();
  const billed = "0.020000";
  if (/^(hi|hello|hey|thanks|thank you)\b/.test(lower.trim()) && ask.length < 24)
    return {
      reply: "Tell me what the agent should do, or ask me to change the current prompt (for example: make it more concise).",
      proposal: null,
      billed_usd: billed,
    };
  if (current.trim() && /(concise|shorter|shorten|tighten|trim)/.test(lower)) {
    const lines = current.split("\n");
    const kept = lines
      .filter((l, i) => l.trim() === "" || l.startsWith("#") || i < 2 || /^\s*[-\d]/.test(l))
      .map((l) => l.replace(/\s*\([^)]*\)/g, "").replace(/, (and|or) [^.]*\./, "."));
    const prompt = kept
      .join("\n")
      .replace(/\n{3,}/g, "\n\n")
      .trim();
    return {
      reply: "I kept the structure and every rule, cut the parenthetical asides and shortened the longer lines.",
      proposal: { prompt, begin_message: greeting, dynamic_variables: scanPlaceholders(prompt, greeting).names },
      billed_usd: billed,
    };
  }
  if (current.trim() && /(friendl|warm|polite|tone)/.test(lower)) {
    const prompt = `${current.trim()}\n\n## Tone\n- Sound warm and unhurried. Use the caller's name once you know it.\n- Acknowledge what the caller said before answering.\n- Keep each turn to one or two short sentences.`;
    return {
      reply: "I added a short tone section at the end; the rest of the prompt is unchanged.",
      proposal: { prompt, begin_message: greeting, dynamic_variables: scanPlaceholders(prompt, greeting).names },
      billed_usd: billed,
    };
  }
  const topic =
    ask
      .replace(/^(an?|the)\s+/i, "")
      .replace(/[.?!]+$/, "")
      .trim() || "a phone agent";
  const prompt = `## Role
You are ${/^(a|an)\s/i.test(ask) ? ask.replace(/[.?!]+$/, "") : `the voice agent for ${topic}`} at {{company_name}}. You answer phone calls, help callers quickly, and hand over to a person when you cannot help.

## How to handle a call
1. Greet the caller and ask how you can help.
2. Find out what they need with one question at a time.
3. When booking or changing anything, collect the caller's full name, phone number and the details you need, then read them back to confirm.
4. If the caller asks for something you cannot do, offer to take a message for the team.

## Rules
- Keep each turn to one or two short sentences; this is a phone call.
- Never make up prices, policies or availability. Say you will check and take a message.
- If the caller describes an emergency, tell them to call emergency services.
- Before ending, summarise what happens next and thank the caller.`;
  const begin = "Thanks for calling {{company_name}}. How can I help you today?";
  return {
    reply: `Here is a first draft for ${topic}. It declares {{company_name}}; set its default in the variables list so test calls use your business name.`,
    proposal: { prompt, begin_message: begin, dynamic_variables: scanPlaceholders(prompt, begin).names },
    billed_usd: billed,
  };
}
