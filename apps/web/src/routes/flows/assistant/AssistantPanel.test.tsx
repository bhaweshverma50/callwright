import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse, delay } from "msw";
import { describe, expect, it, vi } from "vitest";
import { env } from "../../../lib/env";
import { server } from "../../../mocks/node";
import { TooltipProvider } from "../../../components/Tooltip";
import type { FlowGraph } from "../../../api/flows";
import { AssistantPanel } from "./AssistantPanel";

const EMPTY: FlowGraph = { nodes: [], edges: [], viewport: { x: 0, y: 0, zoom: 1 } };

describe("AssistantPanel", () => {
  it("shows the first message and the thinking line while the assistant works", async () => {
    server.use(
      http.post(`${env.apiBaseUrl}/flows/:id/assistant`, async () => {
        await delay(400);
        return HttpResponse.json({ message: "Done.", operations: [], issues: [], base_revision: 1, proposed_graph: EMPTY, flow_name: null });
      }),
    );
    const user = userEvent.setup();
    sessionStorage.clear();
    render(
      <TooltipProvider>
        <AssistantPanel flowId="flw_first" revision={1} graph={EMPTY} dirty={false} pending={false} onProposal={vi.fn()} />
      </TooltipProvider>,
    );
    await user.type(screen.getByPlaceholderText("Describe a change to the flow"), "Add a goodbye step{Enter}");
    expect(await screen.findByText("Add a goodbye step")).toBeInTheDocument();
    expect(screen.getByRole("status", { name: "Assistant is working" })).toBeInTheDocument();
    expect(screen.queryByText("Build with the assistant")).not.toBeInTheDocument();
    expect(await screen.findByText("Done.")).toBeInTheDocument();
  });
});
