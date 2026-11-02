import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { store } from "../../../mocks/agents/store";
import { sim } from "../../../mocks/sim/store";
import { renderApp, signInDemo } from "../../../test/render";
import { clampCount, generateLabel } from "./GenerateDialog";

const deskId = () => store().agents.find((a) => a.name === "Front desk agent")!.id;

async function openGenerate() {
  await signInDemo();
  const user = userEvent.setup();
  renderApp(`/agents/${deskId()}/testing?tab=cases`);
  await screen.findByText("Model disclosure", undefined, { timeout: 5000 });
  await user.click(screen.getByRole("button", { name: "Generate" }));
  const dialog = await screen.findByRole("dialog", { name: "Generate test cases" });
  return { user, dialog };
}

describe("count rules (FR-033)", () => {
  it("clamps to 1..20 and keeps an empty field while typing", () => {
    expect(clampCount("25")).toBe("20");
    expect(clampCount("0")).toBe("1");
    expect(clampCount("7")).toBe("7");
    expect(clampCount("")).toBe("");
    expect(clampCount("3a")).toBe("3");
    expect(generateLabel(1)).toBe("Generate 1 test case");
    expect(generateLabel(20)).toBe("Generate 20 test cases");
  });
});

describe("GenerateDialog (T091)", () => {
  it("turns 25 into 20 and 0 into 1, with singular and plural labels", async () => {
    const { user, dialog } = await openGenerate();
    const count = within(dialog).getByRole("textbox", { name: "How many" });
    expect(within(dialog).getByRole("button", { name: "Generate 5 test cases" })).toBeInTheDocument();
    await user.clear(count);
    await user.type(count, "25");
    expect(count).toHaveValue("20");
    expect(within(dialog).getByRole("button", { name: "Generate 20 test cases" })).toBeInTheDocument();
    await user.clear(count);
    await user.type(count, "0");
    expect(count).toHaveValue("1");
    expect(within(dialog).getByRole("button", { name: "Generate 1 test case" })).toBeInTheDocument();
  });

  it('sends category null for "All categories" with an Idempotency-Key, then saves only kept drafts', async () => {
    const { user, dialog } = await openGenerate();
    expect(within(dialog).getByRole("combobox", { name: "Category" })).toHaveTextContent("All categories");
    const count = within(dialog).getByRole("textbox", { name: "How many" });
    await user.clear(count);
    await user.type(count, "3");
    await user.click(within(dialog).getByRole("button", { name: "Generate 3 test cases" }));
    const review = await screen.findByRole("dialog", { name: "Review drafted test cases" });
    const sent = sim().bodies.filter((b) => b.path === "/test-cases/generate");
    expect(sent).toHaveLength(1);
    expect(sent[0]!.body).toMatchObject({ category: null, count: 3 });

    const boxes = within(review).getAllByRole("checkbox");
    expect(boxes).toHaveLength(3);
    await user.click(boxes[0]!);
    await user.click(within(review).getByRole("button", { name: "Save 2 test cases" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    const saved = sim().bodies.filter((b) => b.path === "/test-cases/import");
    expect((saved.at(-1)!.body as { test_cases: unknown[] }).test_cases).toHaveLength(2);
  });
});

describe("manual override (FR-009)", () => {
  it("marks a failed result passed, labels it manual and updates the run totals", async () => {
    await signInDemo();
    const user = userEvent.setup();
    renderApp(`/agents/${deskId()}/testing?tab=cases`);
    const results = await screen.findByRole("list", { name: "Results" }, { timeout: 5000 });
    const passed = () => within(screen.getByRole("group", { name: "Run totals" })).getByText("Passed").nextElementSibling;
    expect(passed()).toHaveTextContent("7");
    await user.click(within(results).getByRole("button", { name: /System prompt leak/ }));
    const verdict = within(results).getByRole("group", { name: "Verdict for System prompt leak" });
    await user.click(within(verdict).getByRole("button", { name: "Mark passed" }));
    await waitFor(() => expect(passed()).toHaveTextContent("8"));
    expect(within(results).getByRole("button", { name: /System prompt leak/ })).toHaveTextContent("Manual");
    expect(within(results).getByText(/Judge failed/)).toBeInTheDocument();
  });
});
