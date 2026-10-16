/**
 * Readable names for AgentConfig paths (T061, FR-025): version compare, the error summary and
 * warnings all name fields the way the editor labels them ("System prompt", "Voice speed"), never
 * as JSON pointers. Keyed list items read as "Variable order_id" or "Pronunciation of SQL".
 */
import { formatMs, formatMultiplier, formatPercentOfNormal, formatSeconds } from "../editor/formatters";

export const PATH_LABELS: Record<string, string> = {
  "/name": "Agent name",
  "/schema_version": "Format version",
  "/type": "Agent type",
  "/language": "Language",
  "/llm": "Language model",
  "/llm/provider": "Model provider",
  "/llm/model": "Language model",
  "/llm/temperature": "Temperature",
  "/prompt": "System prompt",
  "/begin_message": "Greeting",
  "/start_speaker": "Who speaks first",
  "/dynamic_variables": "Variables",
  "/stt": "Speech recognition",
  "/stt/provider": "Speech recognition provider",
  "/stt/model": "Speech recognition model",
  "/tts": "Voice",
  "/tts/provider": "Voice provider",
  "/tts/model": "Voice model",
  "/tts/voice_id": "Voice",
  "/tts/speed": "Voice speed",
  "/tts/expressiveness": "Expressiveness",
  "/tts/volume": "Volume",
  "/noise_cancellation": "Noise cancellation",
  "/noise_cancellation/provider": "Noise cancellation",
  "/noise_cancellation/model": "Noise cancellation",
  "/call_behavior": "Call behaviour",
  "/call_behavior/end_on_silence_s": "End call after silence",
  "/call_behavior/max_duration_s": "Maximum call duration",
  "/call_behavior/ring_duration_ms": "Ring time",
  "/call_behavior/interruption_sensitivity": "Interruption sensitivity",
  "/call_behavior/responsiveness": "Responsiveness",
  "/advanced": "Advanced settings",
  "/advanced/webhook_url": "Webhook address",
  "/advanced/webhook_timeout_ms": "Webhook timeout",
  "/advanced/voicemail_detection": "Voicemail",
  "/advanced/voicemail_detection/enabled": "Voicemail detection",
  "/advanced/voicemail_detection/action": "When voicemail answers",
  "/advanced/voicemail_detection/message": "Voicemail message",
  "/advanced/dtmf": "Keypad input",
  "/advanced/dtmf/enabled": "Keypad input",
  "/advanced/dtmf/timeout_ms": "Keypad pause",
  "/advanced/dtmf/termination_key": "End key",
  "/advanced/dtmf/digits": "Digit limit",
  "/advanced/background_audio": "Background audio",
  "/advanced/background_audio/enabled": "Background audio",
  "/advanced/background_audio/source": "Background sound",
  "/advanced/background_audio/source/kind": "Background sound",
  "/advanced/background_audio/source/id": "Background sound",
  "/advanced/background_audio/source/key": "Background sound",
  "/advanced/background_audio/volume": "Background volume",
  "/advanced/analysis_model": "Analysis model",
  "/advanced/analysis_model/provider": "Analysis model provider",
  "/advanced/analysis_model/model": "Analysis model",
  "/advanced/pronunciation": "Pronunciation dictionary",
  "/advanced/recording": "Call recording",
  "/tool_ids": "Tools",
  "/kb_ids": "Knowledge bases",
  "/flow": "Flow",
  "/evals": "Quality checks",
  "/tools": "Tool definitions",
  "/note": "Version note",
};

const KEYED = /^(\/dynamic_variables|\/advanced\/pronunciation|\/tool_ids|\/kb_ids)\[([^\]]*)\](\/.*)?$/;

/** Readable name for a JSON pointer, including keyed list items. */
export function labelFor(path: string): string {
  const k = KEYED.exec(path);
  if (k) {
    const [, list, key, rest] = k;
    if (list === "/dynamic_variables")
      return rest === "/default" ? `Default for ${key}` : rest === "/description" ? `Description of ${key}` : `Variable ${key}`;
    if (list === "/advanced/pronunciation") return rest === "/replacement" ? `Pronunciation of "${key}"` : `Word "${key}"`;
    return list === "/tool_ids" ? `Tool ${key}` : `Knowledge base ${key}`;
  }
  return PATH_LABELS[path] ?? PATH_LABELS[path.replace(/\/\d+$/, "")] ?? path.split("/").filter(Boolean).pop()?.replace(/_/g, " ") ?? path;
}

/** Long text gets a line diff in compare instead of old and new values side by side. */
export const isLongText = (path: string) => path === "/prompt" || path === "/begin_message" || path === "/advanced/voicemail_detection/message";

/** A value as people read it in compare ("1.5 s", "On", "None"). */
export function formatValue(path: string, v: unknown): string {
  if (v === null || v === undefined || v === "") return "None";
  if (typeof v === "boolean") return v ? "On" : "Off";
  if (typeof v === "number") {
    if (path.endsWith("_ms")) return formatMs(v);
    if (path.endsWith("_s")) return formatSeconds(v);
    if (path === "/tts/speed") return formatMultiplier(v);
    if (path.endsWith("volume")) return formatPercentOfNormal(v);
    return String(v);
  }
  if (typeof v === "string") {
    if (path === "/start_speaker") return v === "user" ? "Caller speaks first" : "Agent speaks first";
    if (path === "/stt/model" && !v) return "Auto";
    return v;
  }
  if (typeof v === "object") {
    const o = v as Record<string, unknown>;
    if ("provider" in o && "model" in o) return `${o.provider} / ${o.model ?? "Auto"}`;
    if ("name" in o) return o.default ? `${o.name} (default ${o.default})` : String(o.name);
    if ("word" in o) return `${o.word} said as ${o.replacement}`;
    if ("kind" in o) return String(o.id ?? o.key);
    return JSON.stringify(v);
  }
  return String(v);
}

export type EditorSection = "basics" | "voice" | "behaviour" | "advanced";

/** The editor tab that holds a field, so the error summary can open it before focusing. */
export function sectionOf(pointer: string): EditorSection {
  if (/^\/(stt|tts|noise_cancellation)/.test(pointer)) return "voice";
  if (pointer.startsWith("/call_behavior")) return "behaviour";
  if (pointer.startsWith("/advanced")) return "advanced";
  return "basics";
}

/** DOM id for the control of a pointer (`/tts/voice_id` -> `f-tts-voice_id`). */
export function fieldId(pointer: string): string {
  return `f${pointer.replace(/[^A-Za-z0-9_]+/g, "-")}`.replace(/-+$/, "");
}
