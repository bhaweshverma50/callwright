import { describe, expect, it } from "vitest";
import { PATH_LABELS, fieldId, formatValue, labelFor, objectFields, readableChanges, sectionOf } from "./versionLabels";

/** Every AgentConfig path in data-model.md section 4 (T056). */
const CONFIG_PATHS = [
  "/schema_version",
  "/type",
  "/language",
  "/llm/provider",
  "/llm/model",
  "/llm/temperature",
  "/prompt",
  "/begin_message",
  "/start_speaker",
  "/dynamic_variables",
  "/stt/provider",
  "/stt/model",
  "/tts/provider",
  "/tts/model",
  "/tts/voice_id",
  "/tts/speed",
  "/tts/expressiveness",
  "/tts/volume",
  "/noise_cancellation",
  "/call_behavior/end_on_silence_s",
  "/call_behavior/max_duration_s",
  "/call_behavior/ring_duration_ms",
  "/call_behavior/interruption_sensitivity",
  "/call_behavior/responsiveness",
  "/advanced/webhook_url",
  "/advanced/webhook_timeout_ms",
  "/advanced/voicemail_detection/enabled",
  "/advanced/voicemail_detection/action",
  "/advanced/voicemail_detection/message",
  "/advanced/dtmf/enabled",
  "/advanced/dtmf/timeout_ms",
  "/advanced/dtmf/termination_key",
  "/advanced/dtmf/digits",
  "/advanced/background_audio/enabled",
  "/advanced/background_audio/source",
  "/advanced/background_audio/volume",
  "/advanced/analysis_model",
  "/advanced/pronunciation",
  "/advanced/recording",
  "/advanced/language_switching",
  "/advanced/language_switching/enabled",
  "/advanced/language_switching/languages",
  "/tool_ids",
  "/kb_ids",
  "/flow",
  "/evals",
  "/tools",
];

describe("version labels (T056, FR-025)", () => {
  it("has a readable label for every AgentConfig path", () => {
    const missing = CONFIG_PATHS.filter((p) => !PATH_LABELS[p]);
    expect(missing).toEqual([]);
  });

  it("names keyed list items by their key", () => {
    expect(labelFor("/dynamic_variables[order_id]")).toBe("Variable order_id");
    expect(labelFor("/dynamic_variables[order_id]/default")).toBe("Default for order_id");
    expect(labelFor("/advanced/pronunciation[sql]/replacement")).toBe('Pronunciation of "sql"');
    expect(labelFor("/prompt")).toBe("System prompt");
    expect(labelFor("/tts/speed")).toBe("Voice speed");
    expect(labelFor("/advanced/language_switching/enabled")).toBe("Caller language switching");
    expect(labelFor("/advanced/language_switching/languages")).toBe("Caller languages");
  });

  it("formats values the way the editor shows them", () => {
    expect(formatValue("/call_behavior/ring_duration_ms", 1500)).toBe("1.5 s");
    expect(formatValue("/tts/volume", 1)).toBe("100%");
    expect(formatValue("/advanced/dtmf/enabled", true)).toBe("On");
    expect(formatValue("/advanced/webhook_url", null)).toBe("None");
    expect(formatValue("/advanced/language_switching/enabled", false)).toBe("Off");
    expect(formatValue("/advanced/language_switching/languages", [])).toBe("All supported languages");
    expect(formatValue("/advanced/language_switching/languages", ["hi", "es"], new Map([["hi", "Hindi"]]))).toBe("Hindi, es");
  });

  it("maps pointers to tabs and field ids", () => {
    expect(sectionOf("/tts/voice_id")).toBe("voice");
    expect(sectionOf("/advanced/webhook_url")).toBe("advanced");
    expect(sectionOf("/call_behavior/max_duration_s")).toBe("behaviour");
    expect(sectionOf("/prompt")).toBe("basics");
    expect(sectionOf("/advanced/language_switching/languages")).toBe("basics");
    expect(fieldId("/tts/voice_id")).toBe("f-tts-voice_id");
    expect(fieldId("/dynamic_variables[order_id]/default")).toBe("f-dynamic_variables-order_id-default");
  });
});

describe("readable tool changes in compare", () => {
  const tool = {
    tool_id: "tool_1",
    name: "press_digit",
    type: "press_digit",
    description: "Press keypad digits",
    config: { delay_ms: 1000 },
    mock_response: null,
  };
  it("splits a whole tool list into one change per tool and drops the id-only entry", () => {
    const { changes, names } = readableChanges([
      { op: "remove" as const, path: "/tool_ids[tool_1]", old: "tool_1" },
      { op: "remove" as const, path: "/tools", old: [tool] },
    ]);
    expect(changes.map((c) => [c.op, c.path])).toEqual([["remove", "/tools[tool_1]"]]);
    expect(labelFor(changes[0]?.path ?? "", names)).toBe("Tool press_digit");
  });
  it("reads tool objects as fields, never JSON", () => {
    expect(objectFields("/tools[tool_1]", tool)).toEqual([
      { label: "Name", value: "press_digit" },
      { label: "Type", value: "Press keypad digits" },
      { label: "Description", value: "Press keypad digits" },
      { label: "Delay", value: formatValue("/tools[tool_1]/config/delay_ms", 1000) },
    ]);
  });
});
