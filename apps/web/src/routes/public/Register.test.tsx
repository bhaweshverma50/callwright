import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, unwrap } from "../../api/client";
import { session } from "../../api/session";
import { env } from "../../lib/env";
import { server } from "../../mocks/node";
import { renderApp } from "../../test/render";
import { DEMO_EMAIL, DEMO_PASSWORD } from "../../mocks/demoAccount";

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

describe("register captcha (Turnstile)", () => {
  const mutableEnv = env as { turnstileSiteKey?: string };
  afterEach(() => {
    mutableEnv.turnstileSiteKey = undefined;
    delete window.turnstile;
  });

  function stubTurnstile() {
    const widget = { callback: (_token: string) => {}, reset: vi.fn() };
    window.turnstile = {
      render: (_el, options) => {
        widget.callback = options.callback;
        return "w1";
      },
      reset: widget.reset,
      remove: vi.fn(),
    };
    return widget;
  }

  it("has no widget and submits without a token when no site key is configured", async () => {
    let body: Record<string, unknown> = {};
    server.use(
      http.post(`${env.apiBaseUrl}/auth/register`, async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ status: "verification_sent" }, { status: 202 });
      }),
    );
    renderApp("/register");
    expect(screen.queryByTestId("turnstile")).not.toBeInTheDocument();
    await fillAndSubmit("new@clinic.example");
    expect(await screen.findByText("Check your email")).toBeInTheDocument();
    expect(body).not.toHaveProperty("captcha_token");
  });

  it("waits for the token, sends it, and resets the widget after a failed submit", async () => {
    mutableEnv.turnstileSiteKey = "site-key";
    const widget = stubTurnstile();
    let body: Record<string, unknown> = {};
    server.use(
      http.post(`${env.apiBaseUrl}/auth/register`, async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ code: "captcha_failed", title: "Captcha check failed", status: 400 }, { status: 400 });
      }),
    );
    renderApp("/register");
    const submit = screen.getByRole("button", { name: "Create account" });
    expect(submit).toBeDisabled();
    await waitFor(() => expect(widget.callback).not.toBe(undefined));
    act(() => widget.callback("tok-1"));
    await waitFor(() => expect(submit).toBeEnabled());
    await fillAndSubmit("new@clinic.example");
    await waitFor(() => expect(body.captcha_token).toBe("tok-1"));
    await waitFor(() => expect(widget.reset).toHaveBeenCalledWith("w1"));
    expect(await screen.findByText(/confirm you are human/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create account" })).toBeDisabled();
  });
});
