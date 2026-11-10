import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { llmCatalog, voiceCatalog } from "../../../mocks/agents/catalog";
import { defaultConfig } from "../../../mocks/agents/rules";
import type { AgentConfig } from "../../../api/agents";
import { CostCard } from "./CostCard";
import { renderWithProviders } from "../../../test/render";

function renderCard(mutate?: (c: AgentConfig) => void) {
  const config = defaultConfig("single_prompt");
  mutate?.(config);
  return renderWithProviders(<CostCard config={config} llm={llmCatalog} voice={voiceCatalog} />);
}

const chain = () => screen.getByRole("list", { name: "This agent's signal chain" });

describe("CostCard (T065, T101, US4)", () => {
  it("shows a line per component and a total equal to their sum", async () => {
    renderCard();
    expect(await screen.findByText("$0.1650")).toBeInTheDocument();
    const c = chain();
    for (const rate of ["$0.0000", "$0.0085", "$0.0165", "$0.0900"]) expect(within(c).getByText(rate)).toBeInTheDocument();
    expect(screen.getByText("$0.0500")).toBeInTheDocument();
  });

  it("marks noise cancellation as not used when it is off", async () => {
    renderCard((c) => (c.noise_cancellation = null));
    expect(await screen.findByText("$0.1650")).toBeInTheDocument();
    expect(within(chain()).getByText("Not used")).toBeInTheDocument();
    expect(within(chain()).queryByText("$0.0000")).not.toBeInTheDocument();
  });

  it("says price unavailable instead of $0.0000 and marks the total incomplete", async () => {
    renderCard((c) => (c.llm.model = "gpt-unpriced"));
    expect(await screen.findByText("Price unavailable")).toBeInTheDocument();
    expect(screen.getByText(/Incomplete/)).toBeInTheDocument();
  });

  it("warns about surcharges for a very long prompt", async () => {
    renderCard((c) => (c.prompt = Array.from({ length: 4000 }, () => "word").join(" ")));
    expect(await screen.findByText("Long prompt: calls may cost more")).toBeInTheDocument();
    expect(screen.getByText("20,000")).toBeInTheDocument();
  });
});
