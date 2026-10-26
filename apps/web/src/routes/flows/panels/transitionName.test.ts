import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { transitionDescription, transitionName } from "./transitionName";

// Shared with the API tests so both sides name transitions the same way. Read at run time: the web
// app is built on its own (Vercel uploads apps/web only), so the type check must not import it.
const FIXTURE = resolve(process.cwd(), "../../services/api/tests/unit/flows/fixtures/transition_names.json");
const vectors = (JSON.parse(readFileSync(FIXTURE, "utf8")) as { vectors: { label: string; name: string }[] }).vectors;

describe("transition names (T110)", () => {
  it.each(vectors)("$label", ({ label, name }) => {
    expect(transitionName(label)).toBe(name);
  });

  it("describes the choice the model sees", () => {
    expect(transitionDescription("Billing", "caller asks about a bill")).toBe("Go to Billing. Use when: caller asks about a bill");
  });
});
