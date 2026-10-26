import { describe, expect, it } from "vitest";
import vectors from "../../../../../../services/api/tests/unit/flows/fixtures/transition_names.json";
import { transitionDescription, transitionName } from "./transitionName";

describe("transition names (T110)", () => {
  it.each(vectors.vectors)("$label", ({ label, name }) => {
    expect(transitionName(label)).toBe(name);
  });

  it("describes the choice the model sees", () => {
    expect(transitionDescription("Billing", "caller asks about a bill")).toBe("Go to Billing. Use when: caller asks about a bill");
  });
});
