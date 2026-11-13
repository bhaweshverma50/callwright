import { screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { StrictMode } from "react";
import { Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { session } from "../../api/session";
import { env } from "../../lib/env";
import { server } from "../../mocks/node";
import { renderApp, renderWithProviders } from "../../test/render";
import { GoogleCallback } from "./GoogleCallback";

const CALLBACK = "/auth/google/callback";

function rememberFlow(state: string, next: string | null = null) {
  sessionStorage.setItem("cw.google", JSON.stringify({ state, next }));
}

function countCompletes() {
  const seen: Record<string, unknown>[] = [];
  server.use(
    http.post(`${env.apiBaseUrl}/auth/google/complete`, async ({ request }) => {
      seen.push((await request.json()) as Record<string, unknown>);
      return HttpResponse.json({ access_token: "mock-access.u.1", refresh_token: "mock-refresh.u.1", token_type: "bearer", expires_in: 3600 });
    }),
  );
  return seen;
}

describe("Google sign-in callback", () => {
  beforeEach(() => sessionStorage.clear());
  afterEach(() => sessionStorage.clear());

  it("posts the code, starts the session and replaces the address", async () => {
    rememberFlow("mock-google-s1", "/billing");
    const { router } = renderApp(`${CALLBACK}?code=mock-google-code&state=mock-google-s1`);
    await waitFor(() => expect(router.state.location.pathname).toBe("/billing"));
    expect(session.isSignedIn()).toBe(true);
    // Replaced, not pushed: going back does not return to the address that holds the code.
    expect(router.state.historyAction).toBe("REPLACE");
    expect(router.state.location.search).toBe("");
    expect(sessionStorage.getItem("cw.google")).toBeNull();
  });

  it("opens the dashboard when no page was remembered", async () => {
    rememberFlow("mock-google-s2");
    const { router } = renderApp(`${CALLBACK}?code=mock-google-code&state=mock-google-s2`);
    await waitFor(() => expect(router.state.location.pathname).toBe("/dashboard"));
  });

  it("posts the code once when React StrictMode mounts the page twice", async () => {
    rememberFlow("strict-state");
    const seen = countCompletes();
    renderWithProviders(
      <StrictMode>
        <Routes>
          <Route path={CALLBACK} element={<GoogleCallback />} />
          <Route path="*" element={<p>landed</p>} />
        </Routes>
      </StrictMode>,
      { router: `${CALLBACK}?code=the-code&state=strict-state` },
    );
    expect(await screen.findByText("landed")).toBeInTheDocument();
    expect(seen).toEqual([{ code: "the-code", state: "strict-state" }]);
    expect(session.accessToken()).toBe("mock-access.u.1");
  });

  it("says the sign-in was cancelled when Google returns access_denied", async () => {
    const seen = countCompletes();
    renderApp(`${CALLBACK}?error=access_denied&state=whatever`);
    expect(await screen.findByRole("heading", { name: "Google sign-in was cancelled" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to sign in" })).toHaveAttribute("href", "/login");
    expect(seen).toEqual([]);
    expect(session.isSignedIn()).toBe(false);
  });

  it("refuses a state this tab did not start", async () => {
    rememberFlow("ours");
    const seen = countCompletes();
    renderApp(`${CALLBACK}?code=c&state=someone-elses`);
    expect(await screen.findByText(/expired or was already used/)).toBeInTheDocument();
    expect(seen).toEqual([]);
    expect(session.isSignedIn()).toBe(false);
  });

  it("shows the API's problem and a way back", async () => {
    rememberFlow("used-state");
    server.use(
      http.post(`${env.apiBaseUrl}/auth/google/complete`, () =>
        HttpResponse.json({ code: "google_email_unverified", title: "Google email not verified", status: 400 }, { status: 400 }),
      ),
    );
    renderApp(`${CALLBACK}?code=c&state=used-state`);
    expect(await screen.findByText(/has not verified that email/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to sign in" })).toBeInTheDocument();
    expect(session.isSignedIn()).toBe(false);
  });
});
