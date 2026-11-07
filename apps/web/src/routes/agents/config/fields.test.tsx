import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { store } from "../../../mocks/agents/store";
import { renderApp, signInDemo } from "../../../test/render";
import { labelFor } from "../versions/versionLabels";
import { CONFIG_FIELDS, SECTION_LABELS, fieldId, sectionOf, type EditorSection } from "./fields";

describe("AgentConfig fields (T056, FR-025)", () => {
  it("maps pointers to editor sections and control ids", () => {
    expect(sectionOf("/tts/voice_id")).toBe("voice");
    expect(sectionOf("/advanced/webhook_url")).toBe("advanced");
    expect(sectionOf("/call_behavior/max_duration_s")).toBe("behaviour");
    expect(sectionOf("/dynamic_variables[order_id]/default")).toBe("basics");
    expect(sectionOf("/advanced/language_switching/languages")).toBe("basics");
    expect(fieldId("/tts/voice_id")).toBe("f-tts-voice_id");
    expect(fieldId("/dynamic_variables[order_id]/default")).toBe("f-dynamic_variables-order_id-default");
  });

  it("names every control in the editor the way version compare names its field", async () => {
    await signInDemo();
    const user = userEvent.setup();
    const agent = store().agents.find((a) => a.name === "Front desk agent")!;
    renderApp(`/agents/${agent.id}/edit`);
    await screen.findByRole("tab", { name: SECTION_LABELS.basics }, { timeout: 5000 });

    const seen: string[] = [];
    for (const section of Object.keys(SECTION_LABELS) as EditorSection[]) {
      await user.click(screen.getByRole("tab", { name: new RegExp(`^${SECTION_LABELS[section]}`) }));
      for (const [pointer, field] of Object.entries(CONFIG_FIELDS)) {
        if (field.section !== section) continue;
        const label = document.getElementById(`${fieldId(pointer)}-label`);
        if (!label) continue;
        expect({ pointer, label: label.textContent }).toEqual({ pointer, label: labelFor(pointer) });
        seen.push(pointer);
      }
    }
    expect(seen.length).toBeGreaterThan(15);
  });
});
