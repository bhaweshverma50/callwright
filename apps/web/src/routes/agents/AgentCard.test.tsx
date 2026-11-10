import { screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";
import type { AgentSummary } from "../../api/agents";
import { renderWithProviders } from "../../test/render";
import { AgentCard } from "./AgentCard";
import { providerLabel } from "./editor/catalogs";

const agent: AgentSummary = {
  id: "agt_01HZZZZZZZZZZZZZZZZZZZZZZZ",
  name: "Desk",
  type: "flow",
  language: "en-US",
  llm_model: "openai/gpt-5.1",
  llm_extra_models: ["openai/gpt-5-mini"],
  voice_label: "Sarah",
  voice_extra_labels: [],
  stt_label: "Deepgram Nova 3",
  stt_extra_labels: ["AssemblyAI Universal"],
  published_version: null,
  has_publish_blockers: false,
  vendor_warnings: [],
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

function renderCard(a: AgentSummary) {
  return renderWithProviders(
    <MemoryRouter>
      <AgentCard agent={a} modelLabel="GPT-5.1" modelExtras={["GPT-5 mini"]} languageLabel="English (US)" onDuplicate={() => {}} onDelete={() => {}} />
    </MemoryRouter>,
  );
}

describe("AgentCard", () => {
  it("shows speech recognition and the other models a flow's nodes use", () => {
    renderCard(agent);
    expect(screen.getByText("Speech")).toBeInTheDocument();
    expect(screen.getByText("Deepgram Nova 3")).toBeInTheDocument();
    const more = screen.getAllByText("+1");
    expect(more).toHaveLength(2);
    expect(more[0]).toHaveAttribute("title", "Also used by flow nodes: GPT-5 mini");
    expect(more[1]).toHaveAttribute("title", "Also used by flow nodes: AssemblyAI Universal");
  });

  it("flags an agent on a vendor the platform cannot run as needing attention", () => {
    renderCard({ ...agent, vendor_warnings: ["Sarvam AI speech recognition is not set up on this platform."] });
    expect(screen.getByText("Needs attention")).toBeInTheDocument();
  });

  it("shows no flag for a healthy agent", () => {
    renderCard(agent);
    expect(screen.queryByText("Needs attention")).not.toBeInTheDocument();
  });
});

describe("providerLabel", () => {
  it("marks providers the platform has no key for", () => {
    expect(providerLabel({ label: "Sarvam AI", available: false })).toBe("Sarvam AI (not set up on this platform)");
    expect(providerLabel({ label: "Deepgram", available: true })).toBe("Deepgram");
    expect(providerLabel({ label: "Deepgram" })).toBe("Deepgram");
  });
});
