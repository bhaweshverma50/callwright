import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { configureWake } from "../api/wakeGate";
import { env } from "../lib/env";
import { server } from "../mocks/node";
import { renderApp, signInDemo } from "../test/render";

const wakingUp = () =>
  HttpResponse.json(
    {
      type: "https://callwright.dev/problems/waking_up",
      title: "Starting the call servers",
      status: 503,
      code: "waking_up",
      detail: "Starting the call servers, this takes about a minute.",
    },
    { status: 503, headers: { "content-type": "application/problem+json", "Retry-After": "45" } },
  );

/** Every API call answers waking_up while `asleep()` is true; then the normal mock API answers. */
function sleepingServers(asleep: () => boolean) {
  server.use(
    http.all(`${env.apiBaseUrl}/*`, () => {
      if (asleep()) return wakingUp();
      return undefined;
    }),
  );
}

describe("waking the call servers (hosted demo)", () => {
  it("covers the app while the servers start, then shows the page without errors", async () => {
    configureWake({ backoffMs: [20] });
    let asleep = true;
    await signInDemo();
    sleepingServers(() => asleep);
    renderApp("/settings");
    expect(await screen.findByRole("heading", { name: "Starting servers" })).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Starting servers" })).toBeInTheDocument();
    asleep = false;
    expect(await screen.findByRole("heading", { name: "Settings" })).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("heading", { name: "Starting servers" })).not.toBeInTheDocument());
    expect(screen.queryByText("Something went wrong")).not.toBeInTheDocument();
  });

  it("offers a retry when the servers do not start in time", async () => {
    configureWake({ backoffMs: [10], timeoutMs: 60 });
    let asleep = true;
    await signInDemo();
    sleepingServers(() => asleep);
    renderApp("/settings");
    expect(await screen.findByRole("heading", { name: "The call servers did not start" })).toBeInTheDocument();
    asleep = false;
    await userEvent.setup().click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("heading", { name: "Settings" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "The call servers did not start" })).not.toBeInTheDocument();
  });
});
