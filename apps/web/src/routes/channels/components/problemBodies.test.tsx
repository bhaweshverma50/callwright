import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { type PhoneNumber, useDeleteNumber } from "../../../api/channels";
import { api, unwrap } from "../../../api/client";
import { env } from "../../../lib/env";
import { problemDetail } from "../../../mocks/http";
import { server } from "../../../mocks/node";
import { renderWithProviders, signInDemo } from "../../../test/render";
import { DeleteNumberDialog } from "./DeleteNumberDialog";
import { OutboundCallDialog } from "./OutboundCallDialog";

/** The extension fields of a problem body (active_call_count, reason, ...) reach the dialogs. */

async function importNumber(outboundAgentId?: string): Promise<PhoneNumber> {
  return unwrap(
    api.POST("/phone-numbers", {
      body: {
        e164: "+14155550100",
        label: "Main",
        termination_address: "trunk.example.com",
        ...(outboundAgentId && { outbound_agent_id: outboundAgentId }),
      },
    }),
  );
}

function DeleteHarness({ number }: { number: PhoneNumber }) {
  const del = useDeleteNumber(number.id);
  return (
    <DeleteNumberDialog
      open
      onOpenChange={vi.fn()}
      what="number"
      name={number.label}
      activeCalls={0}
      onDelete={(whenIdle) => del.mutateAsync(whenIdle)}
      pending={del.isPending}
    />
  );
}

describe("problem bodies keep their extension fields", () => {
  beforeEach(async () => {
    await signInDemo();
  });

  it("a delete refused for live calls switches the dialog to delete-when-idle with the served count", async () => {
    const number = await importNumber();
    server.use(
      http.delete(`${env.apiBaseUrl}/phone-numbers/:id`, () =>
        problemDetail(409, "number_has_active_calls", "Calls are active", { active_call_count: 3 }),
      ),
    );
    renderWithProviders(<DeleteHarness number={number} />);
    await userEvent.setup().click(screen.getByRole("button", { name: "Delete number" }));
    expect(await screen.findByText("3 live calls on this number")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete when idle" })).toBeInTheDocument();
  });

  it("a call to a do-not-call number says so instead of a calling-hours sentence", async () => {
    const agents = await unwrap(api.GET("/agents", { params: { query: { page: 1, page_size: 1 } } }));
    const number = await importNumber(agents.items[0]!.id);
    await unwrap(api.POST("/dnc-entries", { body: { number: "+14155550199" } }));
    renderWithProviders(<OutboundCallDialog open onOpenChange={vi.fn()} number={number} />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Call this number"), "+14155550199");
    await user.click(screen.getByRole("button", { name: "Call now" }));
    expect(await screen.findByText("This number is on your do-not-call list.")).toBeInTheDocument();
    expect(screen.queryByText(/It is .* in/)).toBeNull();
  });

  it("a call outside calling hours names the recipient's local time and zones", async () => {
    const agents = await unwrap(api.GET("/agents", { params: { query: { page: 1, page_size: 1 } } }));
    const number = await importNumber(agents.items[0]!.id);
    server.use(
      http.post(`${env.apiBaseUrl}/outbound-calls`, () =>
        problemDetail(422, "outbound_policy", "Outside calling hours.", {
          reason: "outside_calling_hours",
          to_number: "+14155550199",
          recipient_timezones: ["America/Los_Angeles"],
          timezone_source: "number_region",
          recipient_local_time: "2026-11-08T22:15:00",
          next_allowed_at: null,
        }),
      ),
    );
    renderWithProviders(<OutboundCallDialog open onOpenChange={vi.fn()} number={number} />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Call this number"), "+14155550199");
    await user.click(screen.getByRole("button", { name: "Call now" }));
    const alert = await screen.findByText(/Outside your calling hours for the recipient/);
    await waitFor(() => expect(alert.parentElement).toHaveTextContent(/in America\/Los_Angeles\. No day has calling hours set\./));
  });
});
