import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";
import { createQueryClient } from "../../../app/queryClient";
import { Toaster, TooltipProvider } from "../../../components";
import { MOCK_AGENTS } from "../../../mocks/calls/handlers";
import { qualityStore } from "../../../mocks/quality/handlers";
import { EvaluatorCatalog } from "./EvaluatorCatalog";

const DESK = MOCK_AGENTS[0]!.id; // single prompt
const CLINIC = MOCK_AGENTS[1]!.id; // flow

function renderCatalog(agentId = DESK) {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <TooltipProvider>
        <MemoryRouter>
          <EvaluatorCatalog agentId={agentId} />
          <Toaster />
        </MemoryRouter>
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

const card = async (name: string) => screen.findByTestId(`check-${name}`, undefined, { timeout: 4000 });

describe("EvaluatorCatalog (007 T042, US2 scenarios 1 and 9)", () => {
  it("lists the 12 built-ins for a flow agent alphabetically, judges marked as costing credit", async () => {
    renderCatalog(CLINIC);
    const list = await screen.findByRole("list", { name: "Checks" }, { timeout: 4000 });
    const names = within(list)
      .getAllByRole("heading", { level: 3 })
      .map((h) => h.textContent);
    expect(names).toHaveLength(12);
    expect(names).toEqual([...names].sort((a, b) => a!.localeCompare(b!)));
    expect(within(await card("factual_consistency")).getByText(/Costs credit per call/)).toBeInTheDocument();
    expect(within(await card("anomaly_detection")).getByRole("switch")).not.toBeChecked();
    expect(within(await card("node_dead_end")).getByRole("switch")).toBeChecked();
  });

  it("leaves the four flow-only checks out for a single-prompt agent", async () => {
    renderCatalog(DESK);
    const list = await screen.findByRole("list", { name: "Checks" }, { timeout: 4000 });
    expect(within(list).getAllByRole("heading", { level: 3 })).toHaveLength(8);
    for (const name of ["flow_completion", "node_dead_end", "stuck_loop_detector", "transition_correctness"]) {
      expect(screen.queryByTestId(`check-${name}`)).not.toBeInTheDocument();
    }
    expect(within(await card("audio_silence")).getByRole("switch")).toBeChecked();
    expect(within(await card("latency_slo")).getByRole("switch")).toBeChecked();
  });
});

describe("EvaluatorCard (007 T085, US2 scenarios 10, 11, 13 and 14)", () => {
  it("refuses a sample rate of 150 in the form, with Save disabled", async () => {
    const user = userEvent.setup();
    renderCatalog();
    const intent = await card("intent_fulfillment");
    await user.click(within(intent).getByRole("button", { name: "Intent fulfillment settings" }));
    const rate = within(intent).getByRole("spinbutton", { name: "Sample rate" });
    await user.clear(rate);
    await user.type(rate, "150");
    expect(within(intent).getByText("Enter a whole number from 1 to 100")).toBeInTheDocument();
    expect(within(intent).getByRole("button", { name: "Save settings" })).toBeDisabled();
    await user.clear(rate);
    await user.type(rate, "2.5");
    expect(within(intent).getByText("Enter a whole number from 1 to 100")).toBeInTheDocument();
  });

  it("renders whole-number settings as a stepper and the judge model as a pick list", async () => {
    const user = userEvent.setup();
    renderCatalog(CLINIC);
    const loops = await card("stuck_loop_detector");
    await user.click(within(loops).getByRole("button", { name: "Stuck loops settings" }));
    const visits = within(loops).getByRole("spinbutton", { name: "Visits allowed per node" });
    expect(visits).toHaveAttribute("aria-valuemin", "2");
    expect(visits).toHaveAttribute("aria-valuemax", "10");
    expect(within(loops).getByRole("button", { name: "Increase Visits allowed per node" })).toBeInTheDocument();
    const intent = await card("intent_fulfillment");
    await user.click(within(intent).getByRole("button", { name: "Intent fulfillment settings" }));
    expect(within(intent).getByRole("combobox", { name: "Judge model" })).toHaveTextContent("GPT-5 mini");
  });

  it("shows the same default in the helper text as in the field (3,000 ms)", async () => {
    const user = userEvent.setup();
    renderCatalog();
    const silence = await card("audio_silence");
    await user.click(within(silence).getByRole("button", { name: "Long silences settings" }));
    expect(within(silence).getByRole("spinbutton", { name: "Maximum silence" })).toHaveValue("3000");
    expect(within(silence).getByText("Fails when any silence lasts longer than this. Default 3,000 ms.")).toBeInTheDocument();
  });

  it("offers Discard and Save on the edited card only; Discard restores; the switch saves at once and keeps the edit", async () => {
    const user = userEvent.setup();
    renderCatalog();
    const latency = await card("latency_slo");
    await user.click(within(latency).getByRole("button", { name: "Turn latency settings" }));
    const threshold = within(latency).getByRole("spinbutton", { name: "Latency threshold" });
    await user.click(within(latency).getByRole("button", { name: "Increase Latency threshold" }));
    expect(threshold).toHaveValue("3001");
    expect(within(latency).getByRole("button", { name: "Discard" })).toBeInTheDocument();
    expect(within(await card("audio_silence")).queryByRole("button", { name: "Discard" })).not.toBeInTheDocument();

    await user.click(within(latency).getByRole("switch"));
    await waitFor(() => expect(qualityStore().settings[DESK]?.["evl_builtin_latency_slo"]?.enabled).toBe(false));
    expect(qualityStore().settings[DESK]?.["evl_builtin_latency_slo"]?.overrides).toEqual({});
    expect(threshold).toHaveValue("3001");

    await user.click(within(latency).getByRole("button", { name: "Discard" }));
    expect(within(latency).getByRole("spinbutton", { name: "Latency threshold" })).toHaveValue("3000");

    await user.clear(within(latency).getByRole("spinbutton", { name: "Latency threshold" }));
    await user.type(within(latency).getByRole("spinbutton", { name: "Latency threshold" }), "2500");
    await user.click(within(latency).getByRole("button", { name: "Save settings" }));
    await waitFor(() => expect(qualityStore().settings[DESK]?.["evl_builtin_latency_slo"]?.overrides).toEqual({ threshold_ms: 2500 }));
  });

  it("refuses a fifth headline check", async () => {
    const user = userEvent.setup();
    renderCatalog();
    for (const name of ["audio_silence", "tool_call_correctness"]) {
      await user.click(within(await card(name)).getByRole("button", { name: /^Headline check/ }));
      await waitFor(async () =>
        expect(within(await card(name)).getByRole("button", { name: /^Headline check/ })).toHaveAttribute("aria-pressed", "true"),
      );
    }
    const kb = await card("kb_relevance");
    await user.click(within(kb).getByRole("button", { name: /^Headline check/ }));
    expect(await within(kb).findByText("Up to 4 headline checks per agent")).toBeInTheDocument();
  });
});
