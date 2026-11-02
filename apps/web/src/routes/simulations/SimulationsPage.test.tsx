import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { store } from "../../mocks/agents/store";
import { sim } from "../../mocks/sim/store";
import { renderApp, signInDemo } from "../../test/render";

const agentId = (name: string) => store().agents.find((a) => a.name === name)!.id;
const requests = (path: string) => sim().requests.filter((r) => r.startsWith(`GET ${path}?`));

describe("SimulationsPage (T093)", () => {
  it("fetches again for each agent filter change, shows totals in the tab labels and keeps the filter in the address", async () => {
    await signInDemo();
    const user = userEvent.setup();
    const { router } = renderApp("/simulations");
    // Seeded: 4 batches for Front desk agent plus 3 for others; 4 standalone runs.
    await waitFor(() => expect(screen.getByRole("tab", { name: /Batches/ })).toHaveTextContent("Batches6"));
    expect(screen.getByRole("tab", { name: /Individual runs/ })).toHaveTextContent("Individual runs4");
    expect(requests("/experiments").at(-1)).not.toContain("agent_id");
    const before = requests("/experiments").length;

    await user.click(screen.getByRole("combobox", { name: "Agent" }));
    await user.click(await screen.findByRole("option", { name: "Front desk agent" }));
    const desk = agentId("Front desk agent");
    await waitFor(() => expect(requests("/experiments").length).toBeGreaterThan(before));
    expect(requests("/experiments").at(-1)).toContain(`agent_id=${desk}`);
    expect(requests("/simulation-runs").at(-1)).toContain(`agent_id=${desk}`);
    expect(requests("/simulation-runs").at(-1)).toContain("standalone=true");
    expect(router.state.location.search).toContain(`agent=${desk}`);
    await waitFor(() => expect(screen.getByRole("tab", { name: /Batches/ })).toHaveTextContent("Batches3"));
    expect(screen.getByRole("tab", { name: /Individual runs/ })).toHaveTextContent("Individual runs3");

    const afterDesk = requests("/experiments").length;
    await user.click(screen.getByRole("combobox", { name: "Agent" }));
    await user.click(await screen.findByRole("option", { name: "Billing line" }));
    await waitFor(() => expect(requests("/experiments").length).toBeGreaterThan(afterDesk));
    expect(requests("/experiments").at(-1)).toContain(`agent_id=${agentId("Billing line")}`);
    await waitFor(() => expect(screen.getByRole("tab", { name: /Batches/ })).toHaveTextContent("Batches1"));
    const table = within(screen.getByRole("region", { name: "Batches" })).getByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(2);
  });

  it("reads the agent filter from the address on load", async () => {
    await signInDemo();
    renderApp(`/simulations?agent=${agentId("Billing line")}&tab=runs`);
    await waitFor(() => expect(requests("/simulation-runs").some((r) => r.includes(`agent_id=${agentId("Billing line")}`))).toBe(true));
    expect(await screen.findByRole("link", { name: /Dispute a \$180 charge/ })).toBeInTheDocument();
  });

  it("opens New simulation and asks for an agent and a goal before sending anything", async () => {
    await signInDemo();
    const user = userEvent.setup();
    renderApp("/simulations");
    await user.click(await screen.findByRole("button", { name: "New simulation" }));
    const dialog = await screen.findByRole("dialog", { name: "New simulation" });
    await user.click(within(dialog).getByRole("button", { name: "Continue" }));
    expect(
      within(dialog)
        .getAllByRole("alert")
        .map((a) => a.textContent),
    ).toEqual(["Choose an agent", "Describe what the caller wants"]);
    expect(sim().bodies.filter((b) => b.path === "/simulations/preflight")).toHaveLength(0);
  });
});
