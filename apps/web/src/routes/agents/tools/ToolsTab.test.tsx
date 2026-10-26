import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it } from "vitest";
import type { AgentConfig } from "../../../api/agents";
import { createQueryClient } from "../../../app/queryClient";
import { Toaster, TooltipProvider } from "../../../components";
import { defaultConfig } from "../../../mocks/agents/rules";
import { resetToolStore, seedTool } from "../../../mocks/tools";
import { draftErrors, e164Error, nameError, urlError } from "./forms/fieldRules";
import { ToolsTab, toolSummary } from "./ToolsTab";

function Harness({ initial }: { initial: string[] }) {
  const [config, setConfig] = useState<AgentConfig>(() => ({ ...defaultConfig("single_prompt"), tool_ids: initial }));
  return (
    <>
      <ToolsTab
        agentId="agt_x"
        agentType="single_prompt"
        config={config}
        update={(m) =>
          setConfig((c) => {
            const next = structuredClone(c);
            m(next);
            return next;
          })
        }
      />
      <output data-testid="ids">{(config.tool_ids ?? []).join(",")}</output>
    </>
  );
}

function renderTab(initial: string[] = []) {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <TooltipProvider>
        <MemoryRouter>
          <Harness initial={initial} />
          <Toaster />
        </MemoryRouter>
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

const http = (name: string, mock: string | null = null) =>
  seedTool({
    type: "http",
    name,
    description: `Look up ${name}`,
    mock_response: mock,
    config: {
      method: "POST",
      url: "https://api.example.com/slots",
      parameters: { type: "object", properties: {} },
      headers: [],
      body_template: null,
      timeout_ms: 8000,
      response_mappings: [],
      speak_during_execution: true,
      execution_message: "One moment.",
    },
  });

beforeEach(() => resetToolStore());

describe("ToolsTab (005 T030, T033, T088)", () => {
  it("shows an empty state with both ways to add a tool", async () => {
    renderTab();
    expect(await screen.findByText("No tools yet")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Attach from library" })).toBeInTheDocument();
  });

  it("lists attached tools with a missing canned response badge and detaches them", async () => {
    const lookup = http("lookup_slots");
    const mocked = http("book_slot", '{"ok":true}');
    renderTab([lookup.id, mocked.id]);
    const list = await screen.findByRole("list", { name: "Attached tools" });
    expect(within(list).getByText("lookup_slots")).toBeInTheDocument();
    expect(within(list).getAllByText("No canned response")).toHaveLength(1);
    expect(within(list).getAllByText("POST api.example.com/slots")).toHaveLength(2);
    await userEvent.click(screen.getByRole("button", { name: "Detach lookup_slots" }));
    expect(screen.getByTestId("ids").textContent).toBe(mocked.id);
  });

  it("attaches tools from the library and blocks a second tool with the same name", async () => {
    const a = http("check_slots");
    const b = http("lookup");
    const clash = http("check_slots");
    renderTab([a.id]);
    await screen.findByText("check_slots");
    await userEvent.click(screen.getByRole("button", { name: "Attach" }));
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText("Name in use")).toBeInTheDocument();
    const rows = within(dialog).getAllByRole("checkbox");
    expect(rows.find((r) => r.textContent?.includes("Name in use"))).toBeDisabled();
    await userEvent.click(rows.find((r) => r.textContent?.includes("lookup"))!);
    await userEvent.click(within(dialog).getByRole("button", { name: "Attach 1 tool" }));
    await waitFor(() => expect(screen.getByTestId("ids").textContent).toBe(`${a.id},${b.id}`));
    expect(clash.id).not.toBe(a.id);
  });

  it("creates a tool from a preset and attaches it", async () => {
    renderTab();
    await userEvent.click(await screen.findByRole("button", { name: "New tool" }));
    await userEvent.click(await screen.findByRole("button", { name: /End the call/ }));
    const save = screen.getByRole("button", { name: "Create tool" });
    expect(save).toBeEnabled();
    await userEvent.click(save);
    await waitFor(() => expect(screen.getByTestId("ids").textContent).toMatch(/^tool_/));
  });

  it("keeps Save disabled while a field is invalid", async () => {
    renderTab();
    await userEvent.click(await screen.findByRole("button", { name: "New tool" }));
    await userEvent.click(await screen.findByRole("button", { name: /Transfer call/ }));
    await userEvent.type(screen.getByLabelText("Name"), "transfer_desk");
    await userEvent.type(screen.getByLabelText("When to use it"), "Transfer to the desk");
    const save = screen.getByRole("button", { name: "Create tool" });
    expect(save).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Phone number"), "555-0100");
    expect(await screen.findByText(/Use \+E\.164 form/)).toBeInTheDocument();
    await userEvent.clear(screen.getByLabelText("Phone number"));
    await userEvent.type(screen.getByLabelText("Phone number"), "+14155550100");
    expect(save).toBeEnabled();
  });
});

describe("field rules (T095)", () => {
  it("checks names, numbers and URLs like the API", () => {
    expect(nameError("kb_search")).toMatch(/reserved/);
    expect(nameError("route_to_sales")).toMatch(/reserved/);
    expect(nameError("Bad Name")).toMatch(/lowercase/);
    expect(nameError("ok_name")).toBeNull();
    expect(e164Error("+14155550100")).toBeNull();
    expect(e164Error("14155550100")).toMatch(/E\.164/);
    expect(urlError("http://api.example.com")).toMatch(/https/);
    expect(urlError("http://api.example.com", true)).toBeNull();
    expect(urlError("https://{{host}}.example.com/x")).toMatch(/path and query/);
    expect(urlError("https://api.example.com/p/{{id}}?d={{date}}")).toBeNull();
  });

  it("reports invalid JSON in the parameters and body", () => {
    const tool = http("x");
    const errors = draftErrors({ ...tool }, { parameters: "{", body: "{oops" });
    expect(errors.parameters).toBe("Not valid JSON.");
    expect(errors.body_template).toMatch(/Not valid JSON/);
  });

  it("summarises each type", () => {
    const end = seedTool({ type: "end_call", name: "end_call", description: "d", config: { message: "Bye" } });
    expect(toolSummary(end)).toBe('Says "Bye"');
  });
});
