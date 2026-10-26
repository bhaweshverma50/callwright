import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createQueryClient } from "../../../app/queryClient";
import { TooltipProvider } from "../../../components";
import { resetMockChannels } from "../../../mocks/channels/handlers";
import { signInDemo } from "../../../test/render";
import { WhatsAppChannelDialog, whatsappErrors } from "./WhatsAppChannelDialog";

function setup() {
  const onCreated = vi.fn();
  render(
    <QueryClientProvider client={createQueryClient()}>
      <TooltipProvider>
        <WhatsAppChannelDialog open onOpenChange={() => {}} onCreated={onCreated} />
      </TooltipProvider>
    </QueryClientProvider>,
  );
  return { user: userEvent.setup(), onCreated };
}

const valid = {
  meta_phone_number_id: "106540352242922",
  e164: "+14155550100",
  label: "Support",
  access_token: "EAAG-token",
  verify_token: "verify-123",
  app_secret: "secret",
};

describe("WhatsApp form rules (T085)", () => {
  it("accepts a complete form", () => {
    expect(whatsappErrors(valid)).toEqual({});
  });
  it("needs digits for the ID, E.164, a verify token of 8 to 128 characters and a version format", () => {
    const e = whatsappErrors({ ...valid, meta_phone_number_id: "+1 415", e164: "4155550100", verify_token: "short", graph_api_version: "23" });
    expect(e.meta_phone_number_id).toMatch(/Digits only/);
    expect(e.e164).toMatch(/\+14155550123/);
    expect(e.verify_token).toMatch(/8 to 128/);
    expect(e.graph_api_version).toMatch(/v23\.0/);
  });
});

describe("WhatsAppChannelDialog (T085)", () => {
  beforeEach(async () => {
    resetMockChannels();
    await signInDemo();
  });

  it("prefills the API version and shows the callback address", async () => {
    setup();
    await waitFor(() => expect(screen.getByLabelText("API version")).toHaveValue("v23.0"));
    expect(screen.getByText("https://api.callwright.example/v1/whatsapp/webhook")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /setup guide/i })).toHaveAttribute("href", expect.stringContaining("developers.facebook.com"));
  });

  it("keeps non-secret values and clears only the token when WhatsApp rejects it", async () => {
    const { user, onCreated } = setup();
    await waitFor(() => expect(screen.getByLabelText("API version")).toHaveValue("v23.0"));
    await user.type(screen.getByLabelText("Phone number ID"), valid.meta_phone_number_id);
    await user.type(screen.getByLabelText("Business phone number"), valid.e164);
    await user.type(screen.getByLabelText("Label"), valid.label);
    await user.type(screen.getByLabelText("Access token"), "invalid-token");
    await user.type(screen.getByLabelText("Verify token"), valid.verify_token);
    await user.type(screen.getByLabelText("App secret"), valid.app_secret);
    await user.click(screen.getByRole("button", { name: "Connect" }));
    await waitFor(() =>
      expect(screen.getAllByRole("alert").map((a) => a.textContent)).toEqual(
        expect.arrayContaining([expect.stringContaining("Session has expired")]),
      ),
    );
    expect(screen.getByLabelText("Access token")).toHaveValue("");
    expect(screen.getByLabelText("Phone number ID")).toHaveValue(valid.meta_phone_number_id);
    expect(onCreated).not.toHaveBeenCalled();
    await user.type(screen.getByLabelText("Access token"), "EAAG-good");
    await user.click(screen.getByRole("button", { name: "Connect" }));
    await waitFor(() => expect(onCreated).toHaveBeenCalled());
  });

  it("checks the fields before sending", async () => {
    const { user } = setup();
    await user.click(screen.getByRole("button", { name: "Connect" }));
    await waitFor(() => expect(screen.getAllByRole("alert").length).toBeGreaterThanOrEqual(5));
  });
});
