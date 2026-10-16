import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { api, unwrap } from "../../api/client";
import { isRegisteredSession } from "../../app/auth";
import { session } from "../../app/session";
import { env } from "../../lib/env";
import { DEMO_EMAIL, DEMO_PASSWORD } from "../../mocks/db";
import { server } from "../../mocks/node";
import { renderApp } from "../../test/render";

async function fillAndSubmit(email: string) {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Work email"), email);
  await user.type(screen.getByLabelText("Password", { exact: true }), "correct-horse-battery-9");
  await user.click(screen.getByRole("button", { name: "Create account" }));
}

describe("register (T041, US1.1)", () => {
  it("asks the user to check their email when the API sends a verification link", async () => {
    const { router } = renderApp("/register");
    await fillAndSubmit("new@clinic.example");
    expect(await screen.findByText("Check your email")).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/register");
    expect(session.isSignedIn()).toBe(false);
  });

  it("signs straight in when the API auto-verifies and returns session tokens", async () => {
    // A real session from the mock API, handed back by register as AUTH_AUTO_VERIFY_EMAIL does.
    const tokens = await unwrap(api.POST("/auth/sign-in", { body: { email: DEMO_EMAIL, password: DEMO_PASSWORD } }));
    server.use(http.post(`${env.apiBaseUrl}/auth/register`, () => HttpResponse.json({ status: "signed_in", ...tokens }, { status: 200 })));
    const { router } = renderApp("/register");
    await fillAndSubmit("demo@clinic.example");
    await waitFor(() => expect(router.state.location.pathname).toBe("/dashboard"));
    expect(session.accessToken()).toBe(tokens.access_token);
    expect(screen.queryByText("Check your email")).not.toBeInTheDocument();
  });
});

describe("isRegisteredSession", () => {
  it("accepts only a signed_in body with tokens", () => {
    expect(isRegisteredSession({ status: "verification_sent" })).toBe(false);
    expect(isRegisteredSession({ status: "signed_in" })).toBe(false);
    expect(isRegisteredSession(null)).toBe(false);
    expect(isRegisteredSession({ status: "signed_in", access_token: "a", refresh_token: "r", token_type: "bearer", expires_in: 60 })).toBe(true);
  });
});
