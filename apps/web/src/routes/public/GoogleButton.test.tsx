import { screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { env } from "../../lib/env";
import { server } from "../../mocks/node";
import { renderApp } from "../../test/render";

describe("Continue with Google button", () => {
  it.each(["/login", "/register"])("is shown on %s when the API has Google sign-in on", async (path) => {
    renderApp(path);
    expect(await screen.findByRole("button", { name: "Continue with Google" })).toBeInTheDocument();
  });

  it.each(["/login", "/register"])("is hidden on %s when the API has it off", async (path) => {
    server.use(http.get(`${env.apiBaseUrl}/auth/config`, () => HttpResponse.json({ google_signin: false })));
    renderApp(path);
    await screen.findByRole("heading", { level: 1 });
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.queryByRole("button", { name: "Continue with Google" })).not.toBeInTheDocument();
  });
});
