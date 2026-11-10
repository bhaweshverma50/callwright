import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { TEMPLATES } from "../../mocks/agents/templates";
import { renderApp, signInDemo } from "../../test/render";

const total = TEMPLATES.length;
const flows = TEMPLATES.filter((t) => t.agent_type === "flow");
// A template card is the grid's button that opens a dialog; the empty state's action is not one.
const cards = () => [...document.querySelectorAll<HTMLElement>("[data-tour='template-grid'] button[aria-haspopup='dialog']")];
const chip = (name: RegExp) => screen.getByRole("button", { name });

async function gallery(path = "/agents/templates") {
  await signInDemo();
  const utils = renderApp(path);
  await screen.findByRole("group", { name: "Industry" });
  await waitFor(() => expect(cards().length > 0 || screen.queryByText(/^No templates match/) !== null).toBe(true));
  return utils;
}

describe("TemplatesPage filters", () => {
  it("shows every template, the industries with their counts and both controls", async () => {
    await gallery();
    expect(screen.getByRole("heading", { level: 1, name: "Start from a template" })).toBeInTheDocument();
    expect(cards()).toHaveLength(total);
    expect(chip(/^All\s*\d+$/)).toHaveTextContent(String(total));
    expect(screen.getByRole("radio", { name: "All calls" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "All types" })).toBeChecked();
    for (const label of ["Insurance", "Real estate", "Travel and hospitality", "Logistics and delivery", "Utilities"]) {
      expect(chip(new RegExp(`^${label}`))).toBeInTheDocument();
    }
    // Flow templates carry a Flow badge next to the direction pill.
    expect(within(screen.getByRole("button", { name: /Claim intake/ })).getByText("Flow")).toBeInTheDocument();
    expect(within(screen.getByRole("button", { name: /Mobile support line/ })).queryByText("Flow")).not.toBeInTheDocument();
  });

  it("keeps filters in the URL, updates the counts and follows Back", async () => {
    const user = userEvent.setup();
    const { router } = await gallery();
    await user.click(screen.getByRole("radio", { name: "Outbound" }));
    await waitFor(() => expect(router.state.location.search).toBe("?direction=outbound"));
    const outbound = TEMPLATES.filter((t) => t.direction === "outbound");
    await waitFor(() => expect(cards()).toHaveLength(outbound.length));
    expect(chip(/^All\s*\d+$/)).toHaveTextContent(String(outbound.length));

    await user.click(screen.getByRole("radio", { name: "Flow" }));
    await waitFor(() => expect(router.state.location.search).toBe("?direction=outbound&type=flow"));
    const outFlows = outbound.filter((t) => t.agent_type === "flow");
    await waitFor(() => expect(cards()).toHaveLength(outFlows.length));
    expect(screen.getByRole("heading", { level: 1, name: "Start a flow agent" })).toBeInTheDocument();
    // A chip's count is what selecting it returns.
    const banking = outFlows.filter((t) => t.category === "banking").length;
    expect(chip(/^Banking/)).toHaveTextContent(String(banking));
    await user.click(chip(/^Banking/));
    await waitFor(() => expect(router.state.location.search).toContain("category=banking"));
    await waitFor(() => expect(cards()).toHaveLength(banking));

    await router.navigate(-1);
    await waitFor(() => expect(router.state.location.search).toBe("?direction=outbound&type=flow"));
    await waitFor(() => expect(cards()).toHaveLength(outFlows.length));
    expect(screen.getByRole("radio", { name: "Flow" })).toBeChecked();
  });

  it("preselects the type from the link and ignores values it does not know", async () => {
    await gallery("/agents/templates?type=flow&direction=sideways&category=nothing");
    expect(screen.getByRole("radio", { name: "Flow" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "All calls" })).toBeChecked();
    expect(cards()).toHaveLength(flows.length);
    expect(screen.getByRole("link", { name: /Start from scratch/ })).toHaveAttribute("href", "/agents/new/flow");
  });

  it("starts a blank agent of the selected type, and offers both while the type is All", async () => {
    await gallery("/agents/templates?type=single_prompt");
    expect(screen.getByRole("heading", { level: 1, name: "Start a single-prompt agent" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Start from scratch/ })).toHaveAttribute("href", "/agents/new/single");
    expect(cards()).toHaveLength(TEMPLATES.filter((t) => t.agent_type === "single_prompt").length);
    const user = userEvent.setup();
    await user.click(screen.getByRole("radio", { name: "All types" }));
    expect(await screen.findByRole("link", { name: "Blank single prompt" })).toHaveAttribute("href", "/agents/new/single");
    expect(screen.getByRole("link", { name: "Blank flow" })).toHaveAttribute("href", "/agents/new/flow");
  });

  it("searches by name and writes it to the URL", async () => {
    const user = userEvent.setup();
    const { router } = await gallery();
    await user.type(screen.getByRole("textbox", { name: "Search templates" }), "outage");
    await waitFor(() => expect(router.state.location.search).toBe("?q=outage"), { timeout: 2000 });
    await waitFor(() => expect(cards()).toHaveLength(1));
    expect(screen.getByRole("button", { name: /Outage reporting/ })).toBeInTheDocument();
  });

  it("says when nothing matches and clears every filter", async () => {
    const user = userEvent.setup();
    const { router } = await gallery("/agents/templates?type=flow&direction=inbound&category=telecom");
    expect(await screen.findByText("No templates match these filters")).toBeInTheDocument();
    expect(cards()).toHaveLength(0);
    // The empty industry stays visible and selected so it can be cleared.
    expect(chip(/^Telecom\s*0$/)).toHaveAttribute("aria-pressed", "true");
    await user.click(screen.getByRole("button", { name: "Clear filters" }));
    await waitFor(() => expect(router.state.location.search).toBe(""));
    await waitFor(() => expect(cards()).toHaveLength(total));
    expect(screen.getByRole("radio", { name: "All types" })).toBeChecked();
  });

  it("previews a flow template as steps and creates a flow agent that opens in the builder", async () => {
    const user = userEvent.setup();
    const { router } = await gallery("/agents/templates?type=flow");
    await user.click(screen.getByRole("button", { name: /Claim intake/ }));
    const dialog = await screen.findByRole("dialog", { name: /Claim intake/ });
    const steps = await within(dialog).findByRole("list", { name: "Flow steps" });
    expect(within(steps).getAllByRole("listitem").length).toBeGreaterThan(4);
    expect(within(steps).getByText("Safety check")).toBeInTheDocument();
    expect(within(dialog).getByText("Shared instructions")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Use template" }));
    await waitFor(() => expect(router.state.location.pathname).toMatch(/^\/agents\/agt_[0-9A-Z]{26}\/flow$/), { timeout: 5000 });
  });

  it("creates a single-prompt agent from a template and opens the editor", async () => {
    const user = userEvent.setup();
    const { router } = await gallery("/agents/templates?type=single_prompt");
    await user.click(screen.getByRole("button", { name: /Mobile support line/ }));
    const dialog = await screen.findByRole("dialog", { name: /Mobile support line/ });
    expect(await within(dialog).findByText("Prompt")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Use template" }));
    await waitFor(() => expect(router.state.location.pathname).toMatch(/^\/agents\/agt_[0-9A-Z]{26}\/edit$/), { timeout: 5000 });
  });
});
