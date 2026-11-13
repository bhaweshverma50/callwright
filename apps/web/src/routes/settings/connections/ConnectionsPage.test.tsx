import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http } from "msw";
import { describe, expect, it } from "vitest";
import { connectorStore, seedConnection } from "../../../mocks/connectors/store";
import { json, problemDetail, url } from "../../../mocks/http";
import { server } from "../../../mocks/node";
import { renderApp, signInDemo } from "../../../test/render";

describe("ConnectionsPage (022 US1)", () => {
  it("offers to connect Google when there is no connection", async () => {
    await signInDemo();
    let started = 0;
    server.use(
      http.post(url("/connections/google/start"), () => {
        started += 1;
        return json({ authorization_url: window.location.href, expires_in_s: 600 });
      }),
    );
    const user = userEvent.setup();
    renderApp("/settings/connections");
    expect(await screen.findByText(/read-only Drive access/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Connect Google" }));
    await waitFor(() => expect(started).toBe(1));
  });

  it("shows a healthy connection with its access and the Sheets note", async () => {
    await signInDemo();
    seedConnection();
    renderApp("/settings/connections");
    expect(await screen.findByText("drive.owner@example.com")).toBeInTheDocument();
    expect(screen.getByText("Healthy")).toBeInTheDocument();
    expect(screen.getByText("Drive (read-only)")).toBeInTheDocument();
    expect(screen.getByText("Sheets access is not used until the Google Sheets tool is turned on.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reconnect" })).not.toBeInTheDocument();
  });

  it("offers Reconnect for a revoked connection and when Sheets was not granted", async () => {
    await signInDemo();
    seedConnection({ health: "revoked", health_reason: "invalid_grant" });
    seedConnection({
      account_email: "second@example.com",
      sheets_access: false,
      scopes: ["openid", "email", "https://www.googleapis.com/auth/drive.readonly"],
    });
    renderApp("/settings/connections");
    expect(await screen.findByText("Revoked")).toBeInTheDocument();
    expect(screen.getByText("Sheets access not granted")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Reconnect" })).toHaveLength(2);
  });

  it("explains when Google is not configured on the server", async () => {
    await signInDemo();
    server.use(http.get(url("/connections"), () => json({ items: [], google_configured: false })));
    renderApp("/settings/connections");
    expect(await screen.findByText("Google Drive is not configured on this server")).toBeInTheDocument();
  });

  it("lists the knowledge bases when removal is refused", async () => {
    await signInDemo();
    const conn = seedConnection();
    server.use(
      http.delete(url("/connections/:id"), () =>
        problemDetail(409, "connection_in_use", "Remove the knowledge sources that use this connection first.", {
          users: [{ source_id: "ksrc_1", kb_id: "kb_1", kb_name: "Clinic policies", root_name: "Policies" }],
        }),
      ),
    );
    const user = userEvent.setup();
    renderApp("/settings/connections");
    await user.click(await screen.findByRole("button", { name: `Remove ${conn.account_email}` }));
    await user.click(await screen.findByRole("button", { name: "Remove connection" }));
    expect(await screen.findByText(/This connection is used by Clinic policies/)).toBeInTheDocument();
    expect(connectorStore.connections).toHaveLength(1);
  });
});
