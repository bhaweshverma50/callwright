import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { env } from "../../../lib/env";
import { defaultConfig } from "../../../mocks/agents/rules";
import { server } from "../../../mocks/node";
import { renderWithProviders, signInDemo } from "../../../test/render";
import { AssistantPanel } from "./AssistantPanel";
import { useAgentDraft } from "./useAgentDraft";

function Harness({ prompt }: { prompt: string }) {
  const config = { ...defaultConfig("single_prompt"), prompt };
  const draft = useAgentDraft({ id: null, name: "Desk", config, revision: 0, detail: null }, "single_prompt");
  return (
    <>
      <output data-testid="prompt">{draft.config.prompt}</output>
      <output data-testid="dirty">{draft.dirty ? "dirty" : "clean"}</output>
      <AssistantPanel open onOpenChange={() => {}} draft={draft} agentId={null} />
    </>
  );
}

function renderPanel(prompt = "You answer calls for the clinic.") {
  return renderWithProviders(<Harness prompt={prompt} />, { router: true });
}

describe("AssistantPanel (T079, US6)", () => {
  it("shows the proposal as a difference, applies it without saving, and undoes it", async () => {
    await signInDemo();
    const user = userEvent.setup();
    renderPanel();
    await user.click(screen.getByRole("button", { name: "Make the tone warmer" }));
    expect(await screen.findByText("Proposed changes to the prompt", {}, { timeout: 4000 })).toBeInTheDocument();
    expect(screen.getByText("## Tone")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Apply" }));
    expect(screen.getByTestId("prompt").textContent).toContain("## Tone");
    expect(screen.getByTestId("dirty")).toHaveTextContent("dirty");
    await user.click(screen.getByRole("button", { name: "Undo" }));
    expect(screen.getByTestId("prompt")).toHaveTextContent("You answer calls for the clinic.");
    expect(screen.getByTestId("dirty")).toHaveTextContent("clean");
  });

  it("asks for funds when the balance is empty (402)", async () => {
    await signInDemo();
    server.use(
      http.post(`${env.apiBaseUrl}/prompt-ai/generate`, () =>
        HttpResponse.json({ type: "about:blank", title: "Balance at or below zero", status: 402, code: "insufficient_credit" }, { status: 402 }),
      ),
    );
    const user = userEvent.setup();
    renderPanel();
    await user.type(screen.getByRole("textbox", { name: "Message the assistant" }), "Shorter please{Enter}");
    await waitFor(() => expect(screen.getByText(/Add funds to continue/)).toBeInTheDocument());
    expect(screen.getByRole("link", { name: "Add funds" })).toHaveAttribute("href", "/billing");
  });
});
