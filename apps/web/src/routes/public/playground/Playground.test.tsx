import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { env } from "../../../lib/env";
import { server } from "../../../mocks/node";
import { renderApp } from "../../../test/render";

const demoUrl = `${env.apiBaseUrl}/public/demo`;

describe("home page playground", () => {
  it("offers the switched-on scenarios with a part to play", async () => {
    renderApp("/");
    expect(await screen.findByRole("button", { name: "Call the clinic" })).toBeInTheDocument();
    expect(screen.getByText(/sore throat and a fever/)).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole("radio", { name: "Roadside help" }));
    expect(screen.getByRole("button", { name: "Call roadside help" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Roadside help" })).toHaveAttribute("aria-checked", "true");
  });

  it("only shows scenarios the API switched on", async () => {
    server.use(http.get(demoUrl, () => HttpResponse.json({ agents: ["loan"] })));
    renderApp("/");
    expect(await screen.findByRole("button", { name: "Take the bank's call" })).toBeInTheDocument();
    expect(screen.queryByRole("radio", { name: "Clinic visit" })).not.toBeInTheDocument();
  });

  it("plays the sample call when no demo agent is configured", async () => {
    // The sample call starts when scrolled into view; jsdom has no IntersectionObserver.
    vi.stubGlobal(
      "IntersectionObserver",
      class {
        observe() {}
        unobserve() {}
        disconnect() {}
        takeRecords() {
          return [];
        }
      },
    );
    server.use(http.get(demoUrl, () => HttpResponse.json({ agents: [] })));
    renderApp("/");
    expect(await screen.findByRole("figure", { name: /Sample call/ })).toBeInTheDocument();
    expect(screen.queryByRole("radiogroup", { name: "Scenario" })).not.toBeInTheDocument();
  });
});
