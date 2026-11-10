/**
 * Agent records for the mock API (data-model sections 1, 2 and 7). Lives inside the persisted
 * mock state (`db().agentsStore`), created on first use so older saved mock databases upgrade in
 * place. The demo workspace starts with four agents and a short history; new workspaces start
 * empty so the empty state is reachable.
 */
import type { AgentConfig, AgentDetail, AgentSummary, AgentType, ConfigIssue, VersionRef, VersionSource, VersionSummary } from "../../api/agents";
import { db, save } from "../db";
import { contentHash, defaultConfig, overlay, validateConfig } from "./rules";
import { findVoice } from "./voices";
import { DEMO_EMAIL } from "../demoAccount";

export interface MockAgent {
  id: string;
  workspace_id: string;
  name: string;
  type: AgentType;
  language: string;
  draft_config: AgentConfig;
  draft_revision: number;
  draft_version_id: string;
  pinned_version_id: string | null;
  template_id: string | null;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
}

export interface MockVersion {
  id: string;
  workspace_id: string;
  agent_id: string;
  version_number: number;
  config: AgentConfig;
  content_hash: string;
  source: VersionSource;
  restored_from_version_id: string | null;
  parent_version_id: string | null;
  note: string | null;
  publish_blockers: ConfigIssue[];
  created_by_email: string | null;
  created_at: string;
}

export interface MockAmbient {
  workspace_id: string;
  key: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  created_at: string;
  deleted_at: string | null;
}

export interface AgentStore {
  agents: MockAgent[];
  versions: MockVersion[];
  ambient: MockAmbient[];
  /** Idempotency-Key to created agent id (FR-038). */
  idem: Record<string, string>;
  /** Prompt assistant request times per workspace, for the 20 per minute limit. */
  aiCalls: Record<string, number[]>;
  /** Idempotency-Key to the stored assistant response (charged once). */
  aiIdem: Record<string, unknown>;
}

const DAY = 86_400_000;
const CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";

/** ULID-shaped id: 10 characters of time, 16 random (prefix_ + 26 Crockford base32). */
export function ulid(prefix: string, at = Date.now()): string {
  let t = at;
  let time = "";
  for (let i = 0; i < 10; i++) {
    time = CROCKFORD[t % 32] + time;
    t = Math.floor(t / 32);
  }
  let rand = "";
  for (let i = 0; i < 16; i++) rand += CROCKFORD[Math.floor(Math.random() * 32)];
  return `${prefix}_${time}${rand}`;
}
const iso = (ms: number) => new Date(ms).toISOString();

export function store(): AgentStore {
  const state = db() as ReturnType<typeof db> & { agentsStore?: AgentStore };
  if (!state.agentsStore) {
    state.agentsStore = { agents: [], versions: [], ambient: [], idem: {}, aiCalls: {}, aiIdem: {} };
    seedDemo(state.agentsStore);
    save();
  }
  return state.agentsStore;
}

export function workspaceUploadKeys(ws: string): string[] {
  return store()
    .ambient.filter((a) => a.workspace_id === ws && !a.deleted_at)
    .map((a) => a.key);
}

/** Strips snapshot-only blocks from a draft (tools are never part of the draft). */
function draftOf(config: AgentConfig): AgentConfig {
  const { tools: _tools, ...rest } = config as AgentConfig & { tools?: unknown };
  return rest as AgentConfig;
}

export function createVersion(
  agent: MockAgent,
  config: AgentConfig,
  source: VersionSource,
  opts: { note?: string | null; restoredFrom?: string | null; email?: string | null; at?: number; blockers?: ConfigIssue[] } = {},
): MockVersion {
  const s = store();
  const number = s.versions.filter((v) => v.agent_id === agent.id).reduce((n, v) => Math.max(n, v.version_number), 0) + 1;
  const v: MockVersion = {
    id: ulid("agv", opts.at),
    workspace_id: agent.workspace_id,
    agent_id: agent.id,
    version_number: number,
    config: structuredClone(config),
    content_hash: contentHash(draftOf(config)),
    source,
    restored_from_version_id: opts.restoredFrom ?? null,
    parent_version_id: number === 1 ? null : agent.draft_version_id,
    note: opts.note ?? null,
    publish_blockers: opts.blockers ?? validateConfig(agent.type, config).publish_blockers,
    created_by_email: opts.email === undefined ? DEMO_EMAIL : opts.email,
    created_at: iso(opts.at ?? Date.now()),
  };
  s.versions.push(v);
  return v;
}

export function versionById(id: string | null | undefined): MockVersion | undefined {
  return id ? store().versions.find((v) => v.id === id) : undefined;
}

const ref = (v: MockVersion | undefined): VersionRef | null => (v ? { id: v.id, version_number: v.version_number, created_at: v.created_at } : null);

export function voiceLabel(config: AgentConfig): string {
  return findVoice(config.tts.provider, config.tts.voice_id)?.name ?? config.tts.voice_id;
}

export function toDetail(a: MockAgent): AgentDetail {
  const check = validateConfig(a.type, a.draft_config, { uploadKeys: workspaceUploadKeys(a.workspace_id) });
  return {
    id: a.id,
    name: a.name,
    type: a.type,
    template_id: a.template_id,
    draft_revision: a.draft_revision,
    draft_config: structuredClone(a.draft_config),
    draft_version: ref(versionById(a.draft_version_id))!,
    published_version: ref(versionById(a.pinned_version_id)),
    publish_blockers: check.publish_blockers,
    warnings: check.warnings,
    created_at: a.created_at,
    updated_at: a.updated_at,
  };
}

export function toSummary(a: MockAgent): AgentSummary {
  // Cards show what calls run: the published version's vendors, else the draft's.
  const shown = versionById(a.pinned_version_id)?.config ?? a.draft_config;
  return {
    id: a.id,
    name: a.name,
    type: a.type,
    language: a.language,
    llm_model: `${shown.llm.provider}/${shown.llm.model}`,
    llm_extra_models: [],
    voice_label: voiceLabel(shown),
    voice_extra_labels: [],
    stt_label: `${shown.stt.provider} ${shown.stt.model ?? "(Auto)"}`,
    stt_extra_labels: [],
    vendor_warnings: [],
    published_version: ref(versionById(a.pinned_version_id)),
    has_publish_blockers: validateConfig(a.type, a.draft_config).publish_blockers.length > 0,
    created_at: a.created_at,
    updated_at: a.updated_at,
  };
}

export function toVersionSummary(v: MockVersion, agent: MockAgent): VersionSummary {
  return {
    id: v.id,
    version_number: v.version_number,
    source: v.source,
    note: v.note,
    restored_from_version_number: versionById(v.restored_from_version_id)?.version_number ?? null,
    parent_version_number: versionById(v.parent_version_id)?.version_number ?? null,
    summary: {
      llm_model: v.config.llm.model,
      tts_provider: v.config.tts.provider,
      tts_voice_id: v.config.tts.voice_id,
      tool_count: (v.config.tool_ids ?? []).length,
      kb_count: (v.config.kb_ids ?? []).length,
      node_count: v.config.type === "flow" ? 6 : null,
    },
    created_by_email: v.created_by_email,
    created_at: v.created_at,
    content_hash: v.content_hash,
    is_published: agent.pinned_version_id === v.id,
    is_draft: agent.draft_version_id === v.id,
    has_publish_blockers: v.publish_blockers.length > 0,
  };
}

/** Creates an agent row with version 1 (data-model section 3). */
export function insertAgent(
  ws: string,
  name: string,
  type: AgentType,
  config: AgentConfig,
  source: VersionSource,
  opts: { template_id?: string | null; note?: string | null; at?: number } = {},
): MockAgent {
  const at = opts.at ?? Date.now();
  const agent: MockAgent = {
    id: ulid("agt", at),
    workspace_id: ws,
    name,
    type,
    language: config.language,
    draft_config: draftOf(config),
    draft_revision: 1,
    draft_version_id: "",
    pinned_version_id: null,
    template_id: opts.template_id ?? null,
    created_at: iso(at),
    updated_at: iso(at),
    deleted_at: null,
  };
  store().agents.push(agent);
  const v = createVersion(agent, config, source, { note: opts.note ?? null, at });
  agent.draft_version_id = v.id;
  return agent;
}

/** Saves a new draft: a version only when the content changed (FR-022, FR-023). */
export function saveDraft(
  agent: MockAgent,
  config: AgentConfig,
  source: VersionSource,
  opts: { note?: string | null; restoredFrom?: string | null; at?: number } = {},
) {
  const current = versionById(agent.draft_version_id);
  const draft = draftOf(config);
  const hash = contentHash(draft);
  agent.updated_at = iso(opts.at ?? Date.now());
  if (current && current.content_hash === hash && source === "save") return { created: false, version: current };
  const v = createVersion(agent, config, source, { note: opts.note ?? null, restoredFrom: opts.restoredFrom ?? null, at: opts.at });
  agent.draft_config = draft;
  agent.language = draft.language;
  agent.draft_version_id = v.id;
  agent.draft_revision += 1;
  return { created: true, version: v };
}

// demo seed

const FRONT_DESK_V1 = `You are the front desk for {{company_name}}, a family dental practice. You answer calls, book and move appointments, and answer common questions.

- Greet the caller warmly and ask how you can help.
- To book, collect the patient's full name, date of birth, phone number and the reason for the visit, then offer the next two open times.
- Cleanings take 45 minutes; new-patient exams take 60 minutes.
- If the caller describes severe pain, swelling or bleeding that will not stop, offer the same-day emergency slot.
- Never give medical advice. Offer to have a dentist call back.`;

const FRONT_DESK_V2 = `${FRONT_DESK_V1}

Insurance: the practice accepts most major PPO plans. If the caller asks about a specific plan, take their details and say the billing team will confirm within one business day.
Cancellations need 24 hours notice; late cancellations may be charged $40.`;

const BILLING = `You handle billing questions for {{company_name}} patients.

- Verify the caller's full name and date of birth before discussing any balance.
- Explain statements in plain words: what insurance paid, what the patient owes and when it is due.
- Offer to take a card payment by secure text link, or set up a 3 or 6 month payment plan for balances over $300.
- Disputes: note the charge and the reason, and tell the caller the billing team replies within two business days.`;

const TRIAGE_V1 = `You answer after-hours calls for {{company_name}}. The office is closed.

- Ask what the problem is and how long it has been going on.
- Emergencies (facial swelling, a knocked-out tooth, bleeding that will not stop, trouble breathing): tell the caller to go to the nearest emergency room or call emergency services.
- Everything else: take the caller's name and number and tell them the office calls back after 8 am.`;

const TRIAGE_V2 = `${TRIAGE_V1}
- For a lost filling or a broken tooth without pain, suggest dental wax from a pharmacy until the morning.`;

function seedDemo(s: AgentStore) {
  const user = db().users.find((u) => u.email === DEMO_EMAIL);
  const ws = user?.workspace_id;
  if (!ws) return;
  const now = Date.now();
  // The demo agents were saved before 012 made Multilingual v2 the default voice model.
  const saved = (type: "single_prompt" | "flow") => overlay(defaultConfig(type), { tts: { model: "eleven_flash_v2_5" } });
  const base = (patch: Record<string, unknown>) => overlay(saved("single_prompt"), patch) as AgentConfig;
  const vars = [
    { name: "company_name", default: "Halcyon Dental" },
    { name: "customer_name", default: null },
  ];

  // Front desk: three versions, version 2 published, draft is version 3.
  const fd = insertAgent(ws, "Front desk agent", "single_prompt", base({ prompt: FRONT_DESK_V1, dynamic_variables: [vars[0]!] }), "template", {
    template_id: "healthcare-triage-booking",
    note: "Created from Symptom triage and booking",
    at: now - 34 * DAY,
  });
  saveDraft(
    fd,
    base({ prompt: FRONT_DESK_V2, dynamic_variables: [vars[0]!], begin_message: "Thanks for calling Halcyon Dental. How can I help you today?" }),
    "save",
    {
      note: "Insurance and cancellation policy",
      at: now - 20 * DAY,
    },
  );
  fd.pinned_version_id = fd.draft_version_id;
  saveDraft(
    fd,
    base({
      prompt: FRONT_DESK_V2,
      dynamic_variables: [vars[0]!],
      begin_message: "Thanks for calling Halcyon Dental. How can I help you today?",
      tts: { provider: "elevenlabs", model: "eleven_flash_v2_5", voice_id: "el_sarah", speed: 1.1, expressiveness: 0.9, volume: 1 },
      advanced: {
        webhook_url: "https://hooks.halcyon-dental.com/calls",
        pronunciation: [{ word: "Halcyon", replacement: "HAL-see-on" }],
        language_switching: { enabled: true, languages: ["hi", "es"] },
      },
    }),
    "save",
    { note: "Calmer voice, webhook for the booking system", at: now - 2 * DAY },
  );

  // Billing line: one version, published.
  const bl = insertAgent(
    ws,
    "Billing line",
    "single_prompt",
    base({
      prompt: BILLING,
      dynamic_variables: [vars[0]!],
      llm: { provider: "openai", model: "gpt-5-mini", temperature: 1 },
      begin_message: "Halcyon Dental billing. How can I help with your account?",
    }),
    "create",
    { at: now - 26 * DAY },
  );
  bl.pinned_version_id = bl.draft_version_id;

  // After-hours triage: two versions, not published.
  const tr = insertAgent(
    ws,
    "After-hours triage",
    "single_prompt",
    base({
      prompt: TRIAGE_V1,
      dynamic_variables: [vars[0]!],
      tts: { provider: "cartesia", model: "sonic-2", voice_id: "ca_ella", speed: 1, expressiveness: 0.9, volume: 1 },
      call_behavior: { end_on_silence_s: 20, max_duration_s: 300, ring_duration_ms: 3000, interruption_sensitivity: 0.9, responsiveness: 0.8 },
    }),
    "create",
    { at: now - 12 * DAY },
  );
  saveDraft(
    tr,
    base({
      prompt: TRIAGE_V2,
      dynamic_variables: [vars[0]!],
      tts: { provider: "cartesia", model: "sonic-2", voice_id: "ca_ella", speed: 1, expressiveness: 0.9, volume: 1 },
      call_behavior: { end_on_silence_s: 20, max_duration_s: 300, ring_duration_ms: 3000, interruption_sensitivity: 0.9, responsiveness: 0.8 },
    }),
    "save",
    { at: now - 1 * DAY - 3_600_000 },
  );

  // A flow agent (built in spec 004), so the list shows both types.
  const fl = insertAgent(ws, "Recall reminders", "flow", overlay(saved("flow"), { prompt: "" }) as AgentConfig, "flow_publish", {
    at: now - 8 * DAY,
  });
  fl.pinned_version_id = fl.draft_version_id;
  void s;
}
