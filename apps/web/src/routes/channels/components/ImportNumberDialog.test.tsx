import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { env } from "../../../lib/env";
import { server } from "../../../mocks/node";
import { renderWithProviders, signInDemo } from "../../../test/render";
import { stripScheme, terminationError } from "../validation";
import { ImportNumberDialog } from "./ImportNumberDialog";

function setup() {
  const onImported = vi.fn();
  const onOpenChange = vi.fn();
  renderWithProviders(<ImportNumberDialog open onOpenChange={onOpenChange} onImported={onImported} />);
  return { user: userEvent.setup(), onImported, onOpenChange };
}

const submit = () => screen.getByRole("button", { name: "Import number" });
const alerts = () => screen.getAllByRole("alert").map((a) => a.textContent);

describe("termination address rules (T081, research R14)", () => {
  it.each(["trunk.example.com", "trunk.example.com:5060", "sip:trunk.example.com", "203.0.113.10:5080", "[2001:db8::10]:5061"])("accepts %s", (v) => {
    expect(terminationError(v)).toBeNull();
  });
  it.each(["user@trunk.example.com", "trunk.example.com/path", "trunk.example.com;transport=tcp", "trunk.example.com:70000", "2001:db8::10", ""])(
    "rejects %s",
    (v) => {
      expect(terminationError(v)).not.toBeNull();
    },
  );
  it("strips sip and sips", () => {
    expect(stripScheme(" SIPS:trunk.example.com:5061 ")).toBe("trunk.example.com:5061");
  });
});

describe("ImportNumberDialog (T081)", () => {
  beforeEach(async () => {
    await signInDemo();
  });

  it("shows a message under each required field and sends nothing", async () => {
    let posted = 0;
    server.use(
      http.post(`${env.apiBaseUrl}/phone-numbers`, () => {
        posted += 1;
        return undefined;
      }),
    );
    const { user } = setup();
    await user.click(submit());
    await waitFor(() => expect(alerts()).toHaveLength(3));
    expect(alerts()).toEqual(
      expect.arrayContaining([
        expect.stringContaining("Enter the number"),
        expect.stringContaining("Enter a label"),
        expect.stringContaining("termination address"),
      ]),
    );
    expect(posted).toBe(0);
  });

  it("explains E.164 and a user part in the address", async () => {
    const { user } = setup();
    await user.type(screen.getByLabelText("Phone number"), "415 555 0100");
    await user.type(screen.getByLabelText("Label"), "Main");
    await user.type(screen.getByLabelText("Termination address"), "sip:+14155550100@trunk.example.com");
    await user.click(submit());
    await waitFor(() =>
      expect(alerts()).toEqual(expect.arrayContaining([expect.stringContaining("+14155550123"), expect.stringContaining("no user part")])),
    );
    expect(screen.getByLabelText("Phone number")).toHaveAttribute("aria-invalid", "true");
  });

  it("imports with the sip: prefix stripped", async () => {
    const { user, onImported } = setup();
    await user.type(screen.getByLabelText("Phone number"), "+14155550100");
    await user.type(screen.getByLabelText("Label"), "Main office line");
    await user.type(screen.getByLabelText("Termination address"), "sip:trunk.example-carrier.com:5060");
    await user.click(submit());
    await waitFor(() => expect(onImported).toHaveBeenCalled());
    expect(onImported.mock.calls[0]![0]).toMatchObject({
      e164: "+14155550100",
      termination_address: "trunk.example-carrier.com:5060",
      status: "active",
    });
  });

  it("maps server field errors and duplicates onto the fields", async () => {
    const { user } = setup();
    await user.type(screen.getByLabelText("Phone number"), "+14155550100");
    await user.type(screen.getByLabelText("Label"), "Main");
    await user.type(screen.getByLabelText("Termination address"), "trunk.example.com");
    await user.click(submit());
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
    await user.click(submit());
    await waitFor(() => expect(alerts()).toContain("This number is already connected to Callwright."));
  });
});
