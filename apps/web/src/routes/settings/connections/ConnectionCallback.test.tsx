import { screen, waitFor } from "@testing-library/react";
import { http } from "msw";
import { describe, expect, it } from "vitest";
import { connectorStore } from "../../../mocks/connectors/store";
import { problemDetail, url } from "../../../mocks/http";
import { server } from "../../../mocks/node";
import { renderApp, signInDemo } from "../../../test/render";

describe("ConnectionCallback (022 research R4)", () => {
  it("finishes sign-in and returns to Connections", async () => {
    await signInDemo();
    connectorStore.states.add("state-abcdefghijklmnop");
    const { router } = renderApp("/settings/connections/callback?code=fake-code&state=state-abcdefghijklmnop");
    await waitFor(() => expect(router.state.location.pathname).toBe("/settings/connections"));
    expect(await screen.findByText("Google connected")).toBeInTheDocument();
    expect(connectorStore.connections).toHaveLength(1);
  });

  it("says nothing was connected when Google access was declined", async () => {
    await signInDemo();
    connectorStore.states.add("state-declined-abcdefgh");
    renderApp("/settings/connections/callback?error=access_denied&state=state-declined-abcdefgh");
    expect(await screen.findByText("Google access was not granted")).toBeInTheDocument();
    expect(connectorStore.connections).toHaveLength(0);
  });

  it("explains an expired sign-in link", async () => {
    await signInDemo();
    renderApp("/settings/connections/callback?code=fake-code&state=state-unknown-abcdefgh");
    expect(await screen.findByText("Google sign-in did not finish")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to Connections" })).toBeInTheDocument();
  });

  it.each([
    ["oauth_account_mismatch", "This connection belongs to d***@example.com. Sign in with that account, or add a new connection."],
    ["oauth_scope_missing", "Read-only Google Drive access is required. Connect again and leave the Google Drive box ticked."],
    ["oauth_state_invalid", "This sign-in link expired or was started by someone else. Start again from Connections."],
  ])("explains %s instead of a generic failure", async (code, message) => {
    await signInDemo();
    server.use(
      http.post(url("/connections/google/complete"), () =>
        problemDetail(400, code, "This connection belongs to d***@example.com. Sign in with that account, or add a new connection."),
      ),
    );
    renderApp(`/settings/connections/callback?code=fake-code&state=state-${code.replaceAll("_", "-")}`);
    expect(await screen.findByText(message)).toBeInTheDocument();
  });
});
