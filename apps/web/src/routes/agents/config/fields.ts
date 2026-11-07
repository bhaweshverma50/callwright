/**
 * AgentConfig fields (T056, T061, FR-025): one entry per JSON pointer with the label the editor
 * shows and the editor section that holds it. The editor's controls, its tabs and error jump,
 * the flow builder's settings drawer, version compare, the error summary and warnings all read
 * this table, so a field is named the same way everywhere. Slider labels come from the API's
 * control ranges in the editor; their entries here name them when the catalog is not loaded.
 */

export type EditorSection = "basics" | "voice" | "behaviour" | "advanced";

export const SECTION_LABELS: Record<EditorSection, string> = {
  basics: "Basics",
  voice: "Voice",
  behaviour: "Behaviour",
  advanced: "Advanced",
};

/** `long`: free text that version compare shows as a line diff. */
type Field = { label: string; section: EditorSection; long?: true };
const on =
  (section: EditorSection) =>
  (label: string, long?: true): Field => ({ label, section, long });
const basics = on("basics");
const voice = on("voice");
const behaviour = on("behaviour");
const advanced = on("advanced");

export const CONFIG_FIELDS: Record<string, Field> = {
  "/name": basics("Agent name"),
  "/language": basics("Language"),
  "/llm": basics("Language model"),
  "/llm/provider": basics("Model provider"),
  "/llm/model": basics("Language model"),
  "/llm/temperature": basics("Temperature"),
  "/prompt": basics("System prompt", true),
  "/begin_message": basics("Greeting", true),
  "/start_speaker": basics("Who speaks first"),
  "/dynamic_variables": basics("Variables"),
  // Caller language switching (012) sits under the agent's language on Basics.
  "/advanced/language_switching": basics("Caller language switching"),
  "/advanced/language_switching/enabled": basics("Let callers switch language"),
  "/advanced/language_switching/languages": basics("Caller languages"),
  "/stt": voice("Speech recognition"),
  "/stt/provider": voice("Speech recognition provider"),
  "/stt/model": voice("Speech recognition model"),
  "/tts": voice("Voice"),
  "/tts/provider": voice("Voice provider"),
  "/tts/model": voice("Voice model"),
  "/tts/voice_id": voice("Voice"),
  "/tts/speed": voice("Voice speed"),
  "/tts/expressiveness": voice("Expressiveness"),
  "/tts/volume": voice("Volume"),
  "/noise_cancellation": voice("Noise cancellation"),
  "/noise_cancellation/provider": voice("Noise cancellation"),
  "/noise_cancellation/model": voice("Noise cancellation"),
  "/call_behavior": behaviour("Call behaviour"),
  "/call_behavior/end_on_silence_s": behaviour("End call after silence"),
  "/call_behavior/max_duration_s": behaviour("Maximum call duration"),
  "/call_behavior/ring_duration_ms": behaviour("Ring time"),
  "/call_behavior/interruption_sensitivity": behaviour("Interruption sensitivity"),
  "/call_behavior/responsiveness": behaviour("Responsiveness"),
  "/advanced": advanced("Advanced settings"),
  "/advanced/webhook_url": advanced("Webhook address"),
  "/advanced/webhook_timeout_ms": advanced("Webhook timeout"),
  "/advanced/voicemail_detection": advanced("Voicemail"),
  "/advanced/voicemail_detection/enabled": advanced("Detect voicemail"),
  "/advanced/voicemail_detection/action": advanced("When voicemail answers"),
  "/advanced/voicemail_detection/message": advanced("Voicemail message", true),
  "/advanced/dtmf": advanced("Keypad input"),
  "/advanced/dtmf/enabled": advanced("Listen for keypad input"),
  "/advanced/dtmf/timeout_ms": advanced("Keypad pause"),
  "/advanced/dtmf/termination_key": advanced("End key"),
  "/advanced/dtmf/digits": advanced("Digit limit"),
  "/advanced/background_audio": advanced("Background audio"),
  "/advanced/background_audio/enabled": advanced("Play background audio"),
  "/advanced/background_audio/source": advanced("Background sound"),
  "/advanced/background_audio/source/kind": advanced("Background sound"),
  "/advanced/background_audio/source/id": advanced("Background sound"),
  "/advanced/background_audio/source/key": advanced("Background sound"),
  "/advanced/background_audio/volume": advanced("Background volume"),
  "/advanced/analysis_model": advanced("Analysis model"),
  "/advanced/analysis_model/provider": advanced("Analysis model provider"),
  "/advanced/analysis_model/model": advanced("Analysis model"),
  "/advanced/pronunciation": advanced("Pronunciation dictionary"),
  "/advanced/recording": advanced("Call recording"),
};

/** The field entry for a pointer, or the nearest enclosing one (`/tts/speed/0` -> `/tts/speed`). */
function fieldFor(pointer: string): Field | undefined {
  for (let p = pointer.replace(/\[[^\]]*\].*$/, ""); p; p = p.slice(0, p.lastIndexOf("/"))) {
    const f = CONFIG_FIELDS[p];
    if (f) return f;
  }
  return undefined;
}

/** The label the editor shows for a field pointer. */
export function fieldLabel(pointer: string): string {
  const f = CONFIG_FIELDS[pointer];
  if (!f) throw new Error(`No AgentConfig field ${pointer}`);
  return f.label;
}

/** The editor section that holds a field, so the error summary can open it before focusing. */
export function sectionOf(pointer: string): EditorSection {
  return fieldFor(pointer)?.section ?? "basics";
}

/** Top-level config keys with fields in a section (`voice` -> tts, stt, noise_cancellation). */
export function sectionKeys(section: EditorSection): string[] {
  const keys = Object.entries(CONFIG_FIELDS)
    .filter(([pointer, f]) => f.section === section && pointer.split("/").length === 2)
    .map(([pointer]) => pointer.slice(1));
  return [...new Set(keys)];
}

/** DOM id for the control of a pointer (`/tts/voice_id` -> `f-tts-voice_id`). */
export function fieldId(pointer: string): string {
  return `f${pointer.replace(/[^A-Za-z0-9_]+/g, "-")}`.replace(/-+$/, "");
}
