/**
 * Server rules for the mock API: platform defaults (spec Assumptions, research R23) and
 * `validate_config` (data-model sections 4 and 5, FR-013, FR-014, FR-016). The editor never
 * re-implements these; it calls POST /agents/validate, which runs this function, so the inline
 * errors and the save path cannot disagree (FR-040).
 */
import type { AgentConfig, AgentType, ConfigIssue, ConfigValidationResult } from "../../api/agents";
import { MAX_VARIABLES, VARIABLE_NAME, isReserved, scanPlaceholders } from "../../lib/agentVariables";
import { llmCatalog, sttAutoPrice, voiceCatalog } from "./catalog";
import { findVoice } from "./voices";

export const DEFAULT_GREETING = "Hi, thanks for calling. How can I help you today?";

export function languageDefaults(language: string) {
  return voiceCatalog.languages.find((l) => l.code === language) ?? voiceCatalog.languages.find((l) => l.code === "en-US")!;
}

export function defaultConfig(type: AgentType, language = "en-US"): AgentConfig {
  const lang = languageDefaults(language);
  return {
    schema_version: 1,
    type,
    language: lang.code,
    llm: { provider: llmCatalog.default.provider, model: llmCatalog.default.model, temperature: 1 },
    prompt: "",
    begin_message: DEFAULT_GREETING,
    start_speaker: "agent",
    dynamic_variables: [],
    stt: { provider: lang.stt_default.provider, model: lang.stt_default.model },
    tts: {
      provider: lang.tts_default.provider,
      model: lang.tts_default.model,
      voice_id: lang.tts_default.voice_id,
      speed: 1,
      expressiveness: 0.9,
      volume: 1,
    },
    noise_cancellation: { provider: "sanas", model: "vi" },
    call_behavior: { end_on_silence_s: 30, max_duration_s: 600, ring_duration_ms: 5000, interruption_sensitivity: 0.9, responsiveness: 0.8 },
    advanced: {
      webhook_url: null,
      webhook_timeout_ms: 3000,
      voicemail_detection: { enabled: false, action: "hang_up", message: null },
      dtmf: { enabled: false, timeout_ms: 2500, termination_key: "#", digits: 10 },
      background_audio: { enabled: false, source: null, volume: 0.8 },
      analysis_model: null,
      pronunciation: [],
      recording: "inherit",
    },
    tool_ids: [],
    kb_ids: [],
    flow: null,
    evals: null,
  };
}

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => !!v && typeof v === "object" && !Array.isArray(v);

/** Deep merge of a partial config over a base (arrays and nulls replace). */
export function overlay<T>(base: T, patch: unknown): T {
  if (!isObj(patch) || !isObj(base)) return (patch === undefined ? base : patch) as T;
  const out: Obj = { ...(base as Obj) };
  for (const [k, v] of Object.entries(patch)) {
    if (v === undefined) continue;
    out[k] = isObj(v) && isObj(out[k]) ? overlay(out[k], v) : v;
  }
  return out as T;
}

const num = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

const PRIVATE_HOST = [
  /^localhost$/i,
  /\.local$/i,
  /\.internal$/i,
  /^127\./,
  /^10\./,
  /^192\.168\./,
  /^172\.(1[6-9]|2\d|3[01])\./,
  /^169\.254\./,
  /^0\./,
  /^\[?::1\]?$/,
  /^\[?f[cd][0-9a-f]{2}:/i,
  /^\[?fe80:/i,
  /^metadata\.google\.internal$/i,
];

export function webhookProblem(url: string): { code: string; message: string } | null {
  let u: URL;
  try {
    u = new URL(url);
  } catch {
    return { code: "invalid_format", message: "Enter a full address that starts with https://, for example https://api.example.com/calls." };
  }
  if (u.protocol !== "https:") return { code: "invalid_format", message: "Use a secure address that starts with https://." };
  if (!u.hostname.includes(".") && !u.hostname.startsWith("["))
    return { code: "invalid_format", message: "Enter a full address with a domain name." };
  if (PRIVATE_HOST.some((r) => r.test(u.hostname)))
    return { code: "private_address", message: "Webhooks cannot point to a private or local network address." };
  if (url.length > 2048) return { code: "out_of_range", message: "Keep the address to 2,048 characters or fewer." };
  return null;
}

export interface ValidateContext {
  /** Upload keys this workspace owns (background audio). */
  uploadKeys?: string[];
}

export function validateConfig(type: AgentType, input: unknown, ctx: ValidateContext = {}): ConfigValidationResult {
  const errors: ConfigIssue[] = [];
  const blockers: ConfigIssue[] = [];
  const warnings: ConfigIssue[] = [];
  const err = (pointer: string, code: string, message: string) => errors.push({ pointer, code, message });
  const warn = (pointer: string, code: string, message: string) => warnings.push({ pointer, code, message });
  const block = (pointer: string, code: string, message: string) => blockers.push({ pointer, code, message });

  const base = defaultConfig(type, isObj(input) && typeof input.language === "string" ? input.language : "en-US");
  const c = overlay(base, input) as AgentConfig;
  c.type = type;
  c.schema_version = 1;

  const range = (pointer: string, v: unknown, min: number, max: number, message: string, int = false) => {
    if (!num(v) || v < min || v > max || (int && !Number.isInteger(v))) err(pointer, "out_of_range", message);
  };

  // Language
  const lang = voiceCatalog.languages.find((l) => l.code === c.language);
  if (!lang) err("/language", "not_in_catalog", "Choose a language from the list.");

  // Language model and temperature (FR-007)
  const llmProvider = llmCatalog.providers.find((p) => p.id === c.llm?.provider);
  const llmModel = llmProvider?.models.find((m) => m.id === c.llm?.model);
  if (!llmProvider) err("/llm/provider", "not_in_catalog", "Choose a model provider.");
  else if (!llmModel) err("/llm/model", "not_in_catalog", "Choose a language model.");
  else {
    if (llmModel.withdrawn) block("/llm/model", "withdrawn", `${llmModel.label} is no longer offered. Choose another model before publishing.`);
    if (llmModel.price_per_min_usd === null) block("/llm/model", "unpriced", `${llmModel.label} has no price yet, so the agent cannot go live.`);
    const rule = llmModel.temperature;
    if ("fixed" in rule) {
      if (c.llm.temperature !== rule.fixed)
        warn(
          "/llm/temperature",
          "temperature_fixed",
          `${llmModel.label} only supports temperature ${rule.fixed.toFixed(1)}; it is saved as ${rule.fixed.toFixed(1)}.`,
        );
      c.llm.temperature = rule.fixed;
    } else range("/llm/temperature", c.llm.temperature, rule.min, rule.max, `Temperature must be between ${rule.min} and ${rule.max}.`);
  }

  // Prompt and greeting
  if (type === "single_prompt" && !(c.prompt ?? "").trim()) err("/prompt", "required", "Write the system prompt.");
  if ((c.prompt ?? "").length > 50_000) err("/prompt", "out_of_range", "Keep the prompt to 50,000 characters or fewer.");
  if ((c.begin_message ?? "").length > 1000) err("/begin_message", "out_of_range", "Keep the greeting to 1,000 characters or fewer.");
  if (c.start_speaker !== "agent" && c.start_speaker !== "user") err("/start_speaker", "invalid_format", "Choose who speaks first.");
  const greeting = (c.begin_message ?? "").trim();
  if (c.start_speaker === "agent" && !greeting)
    warn("/begin_message", "generated_greeting", "No greeting set: the agent writes its own opening line from the prompt.");
  if (c.start_speaker === "user" && greeting)
    warn("/begin_message", "greeting_unused", "The greeting is kept but not spoken while the caller speaks first.");

  // Variables (FR-008, FR-016)
  const scan = scanPlaceholders(c.prompt, c.begin_message);
  for (const bad of scan.invalid) warn("/prompt", "invalid_variable", `${bad} is not a valid variable name, so it is spoken as written.`);
  const vars = Array.isArray(c.dynamic_variables) ? c.dynamic_variables : [];
  if (vars.length > MAX_VARIABLES) err("/dynamic_variables", "out_of_range", `An agent can have at most ${MAX_VARIABLES} variables.`);
  const seen = new Set<string>();
  for (const v of vars) {
    const p = `/dynamic_variables[${v.name}]`;
    if (!VARIABLE_NAME.test(v.name ?? "")) {
      err(
        `${p}/name`,
        "invalid_variable",
        `${v.name || "A variable"} is not a valid name. Use letters, digits and underscores, starting with a letter or underscore.`,
      );
      continue;
    }
    if (isReserved(v.name)) err(`${p}/name`, "reserved_variable", `${v.name} is built in and cannot be declared.`);
    if (seen.has(v.name)) err(`${p}/name`, "duplicate_entry", `${v.name} is declared twice.`);
    seen.add(v.name);
    if ((v.default ?? "").length > 2000) err(`${p}/default`, "out_of_range", "Keep the default to 2,000 characters or fewer.");
    const used = scan.names.includes(v.name);
    const hasDefault = (v.default ?? "") !== "";
    if (used && !hasDefault) warn(`${p}/default`, "variable_without_default", `{{${v.name}}} has no default; calls must supply a value.`);
    if (!used && hasDefault) warn(`${p}/default`, "unused_default", `{{${v.name}}} has a default but is not used in the prompt or greeting.`);
  }

  // Speech recognition (FR-011)
  const sttProvider = voiceCatalog.stt.find((p) => p.provider === c.stt?.provider);
  if (!sttProvider) err("/stt/provider", "not_in_catalog", "Choose a speech recognition provider.");
  else {
    const covers = (langs: string[]) => langs.includes(c.language);
    if (c.stt.model == null) {
      if (!sttProvider.supports_auto) err("/stt/model", "required", "Choose a speech recognition model.");
      else if (!sttProvider.models.some((m) => covers(m.languages)))
        err(
          "/stt/provider",
          "stt_language_unsupported",
          `${sttProvider.label} does not recognise ${lang?.label ?? c.language}. Choose another provider.`,
        );
      else if (sttAutoPrice(sttProvider.provider) === null) block("/stt/model", "unpriced", "Auto has no price yet for this provider.");
    } else {
      const m = sttProvider.models.find((x) => x.id === c.stt.model);
      if (!m) err("/stt/model", "not_in_catalog", "Choose a speech recognition model.");
      else {
        if (!covers(m.languages))
          err("/stt/model", "stt_language_unsupported", `${m.label} does not recognise ${lang?.label ?? c.language}. Choose Auto or another model.`);
        if (m.withdrawn) block("/stt/model", "withdrawn", `${m.label} is no longer offered.`);
        if (m.price_per_min_usd === null) block("/stt/model", "unpriced", `${m.label} has no price yet.`);
      }
    }
  }

  // Voice
  const ttsProvider = voiceCatalog.tts.find((p) => p.provider === c.tts?.provider);
  if (!ttsProvider) err("/tts/provider", "not_in_catalog", "Choose a voice provider.");
  else {
    const m = ttsProvider.models.find((x) => x.id === c.tts.model);
    if (!c.tts.model) err("/tts/model", "required", "Choose a voice model.");
    else if (!m) err("/tts/model", "not_in_catalog", "Choose a voice model from the list.");
    else {
      if (m.withdrawn) block("/tts/model", "withdrawn", `${m.label} is no longer offered.`);
      if (m.price_per_min_usd === null) block("/tts/model", "unpriced", `${m.label} has no price yet.`);
    }
    if (!c.tts.voice_id) err("/tts/voice_id", "required", "Choose a voice.");
    else if (!findVoice(ttsProvider.provider, c.tts.voice_id))
      err("/tts/voice_id", "voice_not_in_provider", `This voice is not offered by ${ttsProvider.label}. Choose one of its voices.`);
  }
  range("/tts/speed", c.tts?.speed, 0.5, 2, "Voice speed must be between 0.5x and 2x.");
  range("/tts/expressiveness", c.tts?.expressiveness, 0, 2, "Expressiveness must be between 0 and 2.");
  range("/tts/volume", c.tts?.volume, 0, 2, "Volume must be between 0% and 200% of normal.");

  // Noise cancellation
  if (c.noise_cancellation) {
    const nc = voiceCatalog.noise_cancellation.find((o) => o.provider === c.noise_cancellation!.provider && o.model === c.noise_cancellation!.model);
    if (!nc) err("/noise_cancellation", "not_in_catalog", "Choose a noise cancellation option.");
    else if (nc.price_per_min_usd === null) block("/noise_cancellation", "unpriced", `${nc.label} has no price yet.`);
  }

  // Call behaviour
  const cb = c.call_behavior;
  range("/call_behavior/end_on_silence_s", cb?.end_on_silence_s, 10, 300, "End the call after 10 seconds to 5 minutes of silence.", true);
  range("/call_behavior/max_duration_s", cb?.max_duration_s, 30, 3600, "Maximum call duration must be between 30 seconds and 60 minutes.", true);
  range("/call_behavior/ring_duration_ms", cb?.ring_duration_ms, 0, 30_000, "Ring time must be between 0 and 30 seconds.", true);
  range("/call_behavior/interruption_sensitivity", cb?.interruption_sensitivity, 0, 1, "Interruption sensitivity must be between 0 and 1.");
  range("/call_behavior/responsiveness", cb?.responsiveness, 0, 1, "Responsiveness must be between 0 and 1.");

  // Advanced
  const a = c.advanced;
  if (a.webhook_url != null && a.webhook_url.trim() === "") a.webhook_url = null;
  if (a.webhook_url) {
    const p = webhookProblem(a.webhook_url);
    if (p) err("/advanced/webhook_url", p.code, p.message);
  }
  range("/advanced/webhook_timeout_ms", a.webhook_timeout_ms, 1000, 30_000, "Webhook timeout must be between 1 and 30 seconds.", true);
  const vm = a.voicemail_detection;
  if (vm.enabled && vm.action === "leave_message") {
    const msg = (vm.message ?? "").trim();
    if (!msg) err("/advanced/voicemail_detection/message", "required", "Write the message to leave on voicemail.");
    else if (msg.length > 500) err("/advanced/voicemail_detection/message", "out_of_range", "Keep the voicemail message to 500 characters or fewer.");
  }
  if (a.dtmf.enabled) {
    range("/advanced/dtmf/timeout_ms", a.dtmf.timeout_ms, 1000, 10_000, "Keypad pause must be between 1 and 10 seconds.", true);
    range("/advanced/dtmf/digits", a.dtmf.digits, 1, 99, "Digit limit must be between 1 and 99.", true);
    const key = a.dtmf.termination_key;
    if (key != null && !/^[0-9#*]$/.test(key)) err("/advanced/dtmf/termination_key", "invalid_format", "Choose 0 to 9, # or *, or no end key.");
  }
  const bg = a.background_audio;
  range("/advanced/background_audio/volume", bg.volume ?? 0.8, 0, 3, "Background volume must be between 0% and 300% of normal.");
  if (bg.enabled) {
    const src = bg.source;
    if (!src) err("/advanced/background_audio/source", "required", "Choose a background sound.");
    else if (src.kind === "builtin" && !voiceCatalog.ambient_sounds.some((s) => s.id === src.id))
      err("/advanced/background_audio/source", "not_in_catalog", "Choose a background sound from the list.");
    else if (src.kind === "upload" && ctx.uploadKeys && !ctx.uploadKeys.includes(src.key))
      err("/advanced/background_audio/source", "missing_reference", "This upload was deleted. Choose another sound.");
  }
  if (a.analysis_model) {
    const ok = llmCatalog.providers.find((p) => p.id === a.analysis_model!.provider)?.models.some((m) => m.id === a.analysis_model!.model);
    if (!ok) err("/advanced/analysis_model", "not_in_catalog", "Choose an analysis model from the list.");
  }
  a.pronunciation = (a.pronunciation ?? []).filter((r) => (r.word ?? "").trim() && (r.replacement ?? "").trim());
  if (a.pronunciation.length > 200) err("/advanced/pronunciation", "out_of_range", "Keep the dictionary to 200 entries or fewer.");
  const words = new Set<string>();
  for (const r of a.pronunciation) {
    const key = r.word.trim().toLowerCase();
    const p = `/advanced/pronunciation[${key}]`;
    if (r.word.length > 100) err(`${p}/word`, "out_of_range", "Keep each word to 100 characters or fewer.");
    if (r.replacement.length > 200) err(`${p}/replacement`, "out_of_range", "Keep each pronunciation to 200 characters or fewer.");
    if (words.has(key)) err(`${p}/word`, "duplicate_entry", `"${r.word.trim()}" is listed twice.`);
    words.add(key);
  }
  if (a.recording && !["inherit", "on", "off"].includes(a.recording)) err("/advanced/recording", "invalid_format", "Choose how calls are recorded.");

  return { valid: errors.length === 0, errors, publish_blockers: blockers, warnings, normalized_config: c };
}

/** Canonical JSON (sorted keys) for content hashing (research R3). */
export function canonical(v: unknown): string {
  if (Array.isArray(v)) return `[${v.map(canonical).join(",")}]`;
  if (isObj(v))
    return `{${Object.keys(v)
      .sort()
      .filter((k) => v[k] !== undefined)
      .map((k) => `${JSON.stringify(k)}:${canonical(v[k])}`)
      .join(",")}}`;
  return JSON.stringify(v ?? null);
}

/** 64 hex chars from four FNV-1a passes (stands in for sha256 in the mock). */
export function contentHash(config: unknown): string {
  const s = canonical(config);
  let out = "";
  for (let seed = 0; seed < 4; seed++) {
    let h = 0x811c9dc5 ^ (seed * 0x9e3779b1);
    for (let i = 0; i < s.length; i++) {
      h ^= s.charCodeAt(i);
      h = Math.imul(h, 0x01000193);
    }
    let h2 = h ^ (s.length * (seed + 7));
    h2 = Math.imul(h2 ^ (h2 >>> 15), 0x2c1b3c6d);
    out += (h >>> 0).toString(16).padStart(8, "0") + (h2 >>> 0).toString(16).padStart(8, "0");
  }
  return out;
}
