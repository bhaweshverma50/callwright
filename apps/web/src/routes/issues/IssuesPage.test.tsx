import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { issuesMock } from "../../mocks/issues/store";
import { renderApp, signInDemo } from "../../test/render";

const listRequests = () => issuesMock().requests.filter((r) => r.startsWith("GET /issues?"));
const rows = () =>
  within(screen.getByRole("region", { name: "Issues" }))
    .getAllByRole("row")
    .slice(1);

describe("IssuesPage (T023, T061)", () => {
  it("fetches the list once per filter change and keeps every filter in the address", async () => {
    await signInDemo();
    const user = userEvent.setup();
    const { router } = renderApp("/issues");
    const desk = issuesMock().agents.desk;
    await screen.findByRole("link", { name: /Agent quotes prices/ });
    expect(listRequests().at(-1)).toContain("window_days=14");
    expect(listRequests().at(-1)).toContain("scope=real");
    expect(listRequests().at(-1)).not.toContain("agent_id");

    const step = async (act: () => Promise<void>, expectPart: string) => {
      const before = listRequests().length;
      await act();
      await waitFor(() => expect(listRequests().length).toBe(before + 1));
      expect(listRequests().at(-1)).toContain(expectPart);
    };

    await step(async () => {
      await user.click(screen.getByRole("combobox", { name: "Agent" }));
      await user.click(await screen.findByRole("option", { name: "Front desk agent" }));
    }, `agent_id=${desk}`);
    await step(() => user.click(screen.getByRole("radio", { name: "30 days" })), "window_days=30");
    await step(() => user.click(screen.getByRole("radio", { name: "Real + simulated" })), "scope=real_and_simulated");
    await step(async () => {
      await user.click(screen.getByRole("combobox", { name: "Status" }));
      await user.click(await screen.findByRole("option", { name: "Dismissed" }));
    }, "status=dismissed");

    const search = new URLSearchParams(router.state.location.search);
    expect(Object.fromEntries(search)).toEqual({ agent: desk, window: "30", source: "real_and_simulated", status: "dismissed" });
    await waitFor(() => expect(rows()).toHaveLength(1));
    expect(rows()[0]).toHaveTextContent("Agent repeats the greeting after a pause");
  });

  it("shows readable status labels, hides dismissed and mostly simulated issues by default, and sorts by affected calls", async () => {
    await signInDemo();
    const user = userEvent.setup();
    renderApp("/issues");
    await screen.findByRole("link", { name: /Agent quotes prices/ });
    const titles = rows().map((r) => within(r).getByRole("link").textContent);
    expect(titles).not.toContain("Agent repeats the greeting after a pause");
    expect(titles.some((t) => t?.includes("insurance plan"))).toBe(false);
    const counts = rows().map((r) => Number(within(r).getAllByRole("cell")[2]!.textContent!.match(/^\d+/)![0]));
    expect(counts).toEqual([...counts].sort((a, b) => b - a));

    await user.click(screen.getByRole("combobox", { name: "Status" }));
    const options = (await screen.findAllByRole("option")).map((o) => o.textContent);
    expect(options).toEqual(["All", "Open", "Validating", "Validated", "Applied", "Dismissed"]);
  });

  it("keeps Detect issues disabled with a hint until an agent is chosen, then detects with the window and source", async () => {
    await signInDemo();
    const user = userEvent.setup();
    renderApp("/issues?window=7&source=real_and_simulated");
    const detect = await screen.findByRole("button", { name: "Detect issues" });
    expect(detect).toBeDisabled();
    expect(screen.getByText("Choose an agent to run detection")).toBeInTheDocument();

    await user.click(screen.getByRole("combobox", { name: "Agent" }));
    await user.click(await screen.findByRole("option", { name: "After-hours triage" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Detect issues" })).toBeEnabled());
    expect(screen.queryByText("Choose an agent to run detection")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Detect issues" }));

    expect(await screen.findByText(/Detecting issues in the last 7 days, simulated calls included/)).toBeInTheDocument();
    const body = issuesMock().bodies.find((b) => b.path === "/issues/detect")?.body;
    expect(body).toEqual({ agent_id: issuesMock().agents.triage, window_days: 7, include_simulated: true });
    expect(screen.getByRole("button", { name: "Detecting" })).toBeDisabled();
  });

  it("reports when detection finds nothing", async () => {
    await signInDemo();
    const triage = issuesMock().agents.triage;
    issuesMock().detections[triage] = {
      agent_id: triage,
      status: "completed",
      window_days: 14,
      include_simulated: false,
      window_start: "2026-10-19T00:00:00Z",
      window_end: "2026-11-02T00:00:00Z",
      calls_scanned: 37,
      failures_scanned: 2,
      issues_created: 0,
      issues_updated: 0,
      started_at: "2026-11-02T00:00:00Z",
      finished_at: "2026-11-02T00:01:00Z",
    };
    renderApp(`/issues?agent=${triage}`);
    expect(await screen.findByText("No recurring failures found")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(/between .+ to .+\. 37 calls scanned/);
  });
});
