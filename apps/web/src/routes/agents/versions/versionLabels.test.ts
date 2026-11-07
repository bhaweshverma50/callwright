import { describe, expect, it } from "vitest";
import { formatValue, labelFor, objectFields, readableChanges } from "./versionLabels";

describe("version labels (T056, FR-025)", () => {
  it("names keyed list items by their key", () => {
    expect(labelFor("/dynamic_variables[order_id]")).toBe("Variable order_id");
    expect(labelFor("/dynamic_variables[order_id]/default")).toBe("Default for order_id");
    expect(labelFor("/advanced/pronunciation[sql]/replacement")).toBe('Pronunciation of "sql"');
    expect(labelFor("/prompt")).toBe("System prompt");
    expect(labelFor("/tts/speed")).toBe("Voice speed");
    expect(labelFor("/advanced/language_switching/enabled")).toBe("Let callers switch language");
    expect(labelFor("/tool_ids")).toBe("Tools");
    expect(labelFor("/llm/temperature/0")).toBe("Temperature");
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
