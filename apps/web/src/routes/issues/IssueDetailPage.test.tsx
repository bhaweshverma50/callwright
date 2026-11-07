import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { issuesMock } from "../../mocks/issues/store";
import { renderApp, signInDemo } from "../../test/render";
import { thresholdError } from "./ValidateDialog";

const issueId = (title: string) => issuesMock().issues.find((i) => i.title.startsWith(title))!.issue_id;
const bodies = (suffix: string) => issuesMock().bodies.filter((b) => b.path.endsWith(suffix));

describe("threshold helpers", () => {
  it("checks threshold ranges", () => {
    expect(thresholdError("min_improvement_pp", "4")).toBe("Use a value from 5 to 50.");
    expect(thresholdError("max_regression_pp", "0")).toBeNull();
    expect(thresholdError("min_sample", "4.5")).toBe("Enter a whole number.");
    expect(thresholdError("min_sample", "")).toBe("Enter a number.");
  });
});

describe("IssueDetailPage (T024, T034, T042, T047, T052, T053)", () => {
  it("shows samples, the calibration warning, and drafts then edits a fix as new revisions", async () => {
    await signInDemo();
    const user = userEvent.setup();
    renderApp(`/issues/${issueId("Agent books appointments")}`);
    expect(await screen.findByRole("heading", { name: "Agent books appointments without confirming the date" })).toBeInTheDocument();
    expect(screen.getByText("This check may be wrong.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open calibration" })).toHaveAttribute("href", expect.stringContaining("/calibration?agent="));
    expect((await screen.findAllByText("Moved the appointment without confirming the new time.")).length).toBeGreaterThan(0);

    // No fix yet: the draft form is open with the recommended kind first.
    const form = screen.getByRole("group", { name: "Draft a fix" });
    await user.click(within(form).getByRole("combobox", { name: "Kind of fix" }));
    const kinds = (await screen.findAllByRole("option")).map((o) => o.textContent);
    expect(kinds[0]).toBe("Prompt edit (recommended)");
    expect(kinds).toEqual(["Prompt edit (recommended)", "Add guardrail", "Tool description edit", "Attach knowledge base"]);
    await user.click(screen.getByRole("option", { name: "Add guardrail" }));
    await user.type(within(form).getByRole("textbox", { name: "Guidance" }), "keep the greeting unchanged");
    await user.click(within(form).getByRole("button", { name: "Draft fix" }));

    expect(await screen.findByText(/Current fix: Add guardrail/)).toBeInTheDocument();
    const draft = bodies("/fixes")[0]!.body;
    expect(draft).toEqual({ mode: "ai", kind: "add_guardrail", guidance: "keep the greeting unchanged" });

    await user.click(screen.getByRole("button", { name: "Edit" }));
    const rule = screen.getByRole("textbox", { name: "Rule" });
    await user.clear(rule);
    await user.type(rule, "Never quote a price that is not listed.");
    await user.click(screen.getByRole("button", { name: "Save as new revision" }));

    await waitFor(() => expect(screen.getByText("Written by hand")).toBeInTheDocument());
    expect(bodies("/fixes")[1]!.body).toEqual({
      mode: "manual",
      kind: "add_guardrail",
      payload: { placement: "agent_prompt", rule_text: "Never quote a price that is not listed." },
    });
    const earlier = await screen.findByRole("button", { name: /Revision 1/ });
    expect(earlier).toHaveTextContent("Superseded");
  });

  it("shows the validation estimate, refuses out of range thresholds, then starts validation", async () => {
    await signInDemo();
    const user = userEvent.setup();
    renderApp(`/issues/${issueId("Agent skips the confirm step")}`);
    await user.click(await screen.findByRole("button", { name: "Validate" }));
    const dialog = await screen.findByRole("dialog", { name: "Validate this fix" });
    const estimate = within(dialog).getByRole("group", { name: "Estimate" });
    await waitFor(() => expect(estimate).toHaveTextContent("Simulations34"));
    expect(estimate).toHaveTextContent("Affected calls7");
    expect(bodies("/validate")[0]!.body).toEqual({ dry_run: true, mode: "persona" });

    await user.click(within(dialog).getByRole("button", { name: "Change keep rule" }));
    const improvement = within(dialog).getByRole("spinbutton", { name: "Improvement needed" });
    await user.clear(improvement);
    await user.type(improvement, "60");
    expect(within(dialog).getByText("Use a value from 5 to 50.")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Run 34 simulations" }));
    expect(bodies("/validate")).toHaveLength(1);

    await user.clear(improvement);
    await user.type(improvement, "15");
    await user.click(within(dialog).getByRole("button", { name: "Run 34 simulations" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Validate this fix" })).not.toBeInTheDocument());
    expect(bodies("/validate")[1]!.body).toEqual({ dry_run: false, mode: "persona", min_improvement_pp: 15, max_regression_pp: 5, min_sample: 5 });
    expect(await screen.findByRole("button", { name: "Cancel" })).toBeInTheDocument();
    expect(screen.getAllByText("Validating").length).toBeGreaterThan(0);
  });

  it("shows evidence and earlier attempts, and applies a validated fix without publishing", async () => {
    await signInDemo();
    const user = userEvent.setup();
    renderApp(`/issues/${issueId("Agent quotes prices")}`);
    expect(await screen.findByText("Validation 2 of revision 2")).toBeInTheDocument();
    expect(screen.getAllByText("+50.0 pp").length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: "Control batch" })).toHaveAttribute("href", expect.stringMatching(/^\/simulations\/exp_/));
    await user.click(screen.getByRole("button", { name: /Attempt 1/ }));
    expect(await screen.findByText(/Intent fulfilment dropped by 16.7 pp on affected and guard, more than the 5 pp allowed/)).toBeInTheDocument();
    expect(screen.getByText("Blocks the fix")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Apply fix" }));
    const dialog = await screen.findByRole("dialog", { name: "Apply this fix" });
    await user.click(within(dialog).getByRole("radio", { name: "Create version only" }));
    await user.click(within(dialog).getByRole("button", { name: "Create version" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Apply this fix" })).not.toBeInTheDocument());
    expect(bodies("/apply")[0]!.body).toEqual({ fix_revision: 2, publish: false, release_notes_extra: null });
    expect(await screen.findByText(/The pass rate before and after is shown after 10 calls on the new version/)).toBeInTheDocument();
  });

  it("explains why an unvalidated fix cannot be applied", async () => {
    await signInDemo();
    renderApp(`/issues/${issueId("Agent skips the confirm step")}`);
    const list = await screen.findByRole("list", { name: "Why the fix cannot be applied yet" });
    expect(list).toHaveTextContent("This fix has no passing validation. Validate it first.");
    expect(screen.queryByRole("button", { name: "Apply fix" })).not.toBeInTheDocument();
  });

  it("shows post-apply figures and the recurrence link", async () => {
    await signInDemo();
    renderApp(`/issues/${issueId("Agent still transfers")}`);
    const link = await screen.findByRole("link", { name: "Open the earlier issue" });
    expect(link).toHaveAttribute("href", `/issues/${issueId("Agent transfers billing")}`);

    renderApp(`/issues/${issueId("Agent transfers billing")}`);
    const figures = await screen.findByRole("group", { name: "Headline pass rate before and after" });
    expect(figures).toHaveTextContent("11 of 12 real calls passed");
  });

  it("asks for a note for Other and a target for Duplicate before dismissing", async () => {
    await signInDemo();
    const user = userEvent.setup();
    renderApp(`/issues/${issueId("Agent books appointments")}`);
    await screen.findByRole("heading", { name: /Agent books appointments/ });
    await user.click(within(screen.getByRole("main")).getByRole("button", { name: "Dismiss" }));
    const dialog = await screen.findByRole("dialog", { name: "Dismiss this issue" }, { timeout: 3000 });
    await user.click(within(dialog).getByRole("button", { name: "Dismiss issue" }));
    expect(within(dialog).getByText("Choose why you dismiss this issue.")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("radio", { name: /Other/ }));
    await user.click(within(dialog).getByRole("button", { name: "Dismiss issue" }));
    expect(within(dialog).getByText("Write a note that says why.")).toBeInTheDocument();
    expect(bodies("/dismiss")).toHaveLength(0);

    await user.click(within(dialog).getByRole("radio", { name: /Duplicate/ }));
    await user.click(within(dialog).getByRole("button", { name: "Dismiss issue" }));
    expect(within(dialog).getByText("Choose the issue that covers these failures.")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("combobox", { name: "Duplicate of" }));
    await user.click(await screen.findByRole("option", { name: "Agent quotes prices that are not in the price list" }));
    await user.click(within(dialog).getByRole("button", { name: "Dismiss issue" }));
    await waitFor(() => expect(bodies("/dismiss")).toHaveLength(1));
    expect(bodies("/dismiss")[0]!.body).toEqual({ reason: "duplicate", note: null, duplicate_of: issueId("Agent quotes prices") });
    expect(await screen.findByText(/Dismissed: Duplicate/)).toBeInTheDocument();
  });
});
