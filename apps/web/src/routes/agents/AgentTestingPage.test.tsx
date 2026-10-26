import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { WebCallPanelProps } from "../../components/WebCallPanel";
import { store } from "../../mocks/agents/store";
import { renderApp, signInDemo } from "../../test/render";
import { variablesToSend } from "./AgentTestingPage";

// The call panel has its own tests (WebCallPanel.test.tsx); here it records what the page asks
// it to call.
const panelProps: WebCallPanelProps[] = [];
vi.mock("../../components/WebCallPanel", () => ({
  WebCallPanel: (props: WebCallPanelProps) => {
    panelProps.push(props);
    return (
      <section aria-label="Test call" data-version={props.version} data-variables={JSON.stringify(props.variables ?? null)}>
        <button type="button">Start test call</button>
      </section>
    );
  },
}));

const lastPanel = () => screen.getByRole("region", { name: "Test call" });
const agentNamed = (name: string) => store().agents.find((a) => a.name === name)!;

describe("AgentTestingPage (003 US1)", () => {
  it("calls the draft by default with the variables typed for it", async () => {
    await signInDemo();
    const user = userEvent.setup();
    const agent = agentNamed("Front desk agent");
    renderApp(`/agents/${agent.id}/testing`);

    expect(await screen.findByRole("heading", { level: 1, name: "Test Front desk agent" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Draft" })).toBeChecked();
    expect(lastPanel()).toHaveAttribute("data-version", "draft");
    expect(lastPanel()).toHaveAttribute("data-variables", "null");

    const field = screen.getByRole("textbox", { name: "company_name" });
    expect(field).toHaveAttribute("placeholder", "Halcyon Dental");
    await user.type(field, "Acme Dental");
    await waitFor(() => expect(lastPanel()).toHaveAttribute("data-variables", JSON.stringify({ company_name: "Acme Dental" })));

    // Clearing the field falls back to the default again (nothing sent).
    await user.clear(field);
    await waitFor(() => expect(lastPanel()).toHaveAttribute("data-variables", "null"));
  });

  it("switches to the published version and its variables", async () => {
    await signInDemo();
    const user = userEvent.setup();
    const agent = agentNamed("Front desk agent");
    renderApp(`/agents/${agent.id}/testing`);
    await user.click(await screen.findByRole("radio", { name: "Published" }));
    await waitFor(() => expect(lastPanel()).toHaveAttribute("data-version", "published"));
    expect(screen.getByText(/Published, version 2: what live calls answer with/)).toBeInTheDocument();
    expect(await screen.findByRole("textbox", { name: "company_name" })).toBeInTheDocument();
  });

  it("offers only the draft when nothing is published", async () => {
    await signInDemo();
    const agent = store().agents.find((a) => !a.pinned_version_id && !a.deleted_at && a.type === "single_prompt")!;
    renderApp(`/agents/${agent.id}/testing`);
    const published = await screen.findByRole("radio", { name: "Published" });
    expect(published).toBeDisabled();
    expect(screen.getByText(/Publish the agent to test the live version/)).toBeInTheDocument();
  });

  it("says when the agent does not exist", async () => {
    await signInDemo();
    renderApp("/agents/agt_01JZZZZZZZZZZZZZZZZZZZZZZZ/testing");
    expect(await screen.findByText("Agent not found")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Test call" })).not.toBeInTheDocument();
  });

  it("opens from the editor's Test agent button", async () => {
    await signInDemo();
    const user = userEvent.setup();
    const agent = agentNamed("Front desk agent");
    const { router } = renderApp(`/agents/${agent.id}/edit`);
    const header = await screen.findByRole("heading", { level: 1, name: "Front desk agent" }, { timeout: 5000 });
    const actions = header.closest("header")!;
    await user.click(within(actions).getByRole("button", { name: "Test agent" }));
    await waitFor(() => expect(router.state.location.pathname).toBe(`/agents/${agent.id}/testing`));
    expect(await screen.findByRole("heading", { level: 1, name: "Test Front desk agent" })).toBeInTheDocument();
  });
});

describe("variablesToSend", () => {
  it("sends only declared variables with a value", () => {
    const declared = [{ name: "a", default: "x" }, { name: "b" }];
    expect(variablesToSend(declared, { a: "1", b: "", c: "stray" })).toEqual({ a: "1" });
    expect(variablesToSend(declared, {})).toBeUndefined();
  });
});
