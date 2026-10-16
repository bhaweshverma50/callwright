import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { env } from "../lib/env";
import { server } from "../mocks/node";
import { TooltipProvider } from "./Tooltip";
import { WebCallPanel, type WebCallPanelProps } from "./WebCallPanel";
import { createMockDriver, type MockOptions, type MockStep, type WebCallDriver } from "./webCall";
import { checkMicrophone, createLiveDriver } from "./webCallLive";

const AGENT = "agt_01JABCDEF0123456789ABCDEFG";

const SCRIPT: MockStep[] = [
  { who: "agent", text: "Hi, how can I help?" },
  { who: "caller", text: "Move my cleaning please." },
  { who: "agent", text: "Thursday at 2:15 works.", latency: { stt: 20, llm: 30, tts: 10 } },
];

const FAST: MockOptions = { requestDelayMs: 5, connectDelayMs: 5, wordMs: 5, gapMs: 20, script: SCRIPT };

function renderPanel(props: Partial<WebCallPanelProps> = {}) {
  return render(
    <MemoryRouter>
      <TooltipProvider>
        <WebCallPanel agentId={AGENT} mode="mock" mockOptions={FAST} {...props} />
      </TooltipProvider>
    </MemoryRouter>,
  );
}

/** Wraps a driver and records the order of its steps. */
function spy(inner: WebCallDriver) {
  const calls: string[] = [];
  const driver: WebCallDriver = {
    simulated: inner.simulated,
    checkMicrophone: async () => {
      calls.push("mic");
      return inner.checkMicrophone();
    },
    createSession: async (req, key) => {
      calls.push("session");
      return inner.createSession(req, key);
    },
    connect: async (s, l) => {
      calls.push("connect");
      return inner.connect(s, l);
    },
  };
  return { driver, calls };
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("WebCallPanel", () => {
  it("runs a call: microphone, session, room, transcript with latency, mute, end", async () => {
    const user = userEvent.setup();
    const onEnded = vi.fn();
    const { driver, calls } = spy(createMockDriver(FAST));
    renderPanel({ driver, onEnded });

    expect(screen.getByText("Simulated")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Start test call" }));

    expect(await screen.findByText("On air")).toBeInTheDocument();
    expect(calls).toEqual(["mic", "session", "connect"]);

    const transcript = await screen.findByRole("list", { name: "Transcript" });
    await within(transcript).findByText("Thursday at 2:15 works.");
    expect(within(transcript).getByText("Move my cleaning please.")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Answered in 60 milliseconds/ })).toBeInTheDocument();
    // The greeting has no reply latency, so only one chip.
    expect(screen.getAllByRole("img", { name: /Answered in/ })).toHaveLength(1);

    const mute = screen.getByRole("button", { name: "Mute microphone" });
    await user.click(mute);
    expect(screen.getByRole("button", { name: "Unmute microphone" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("Muted: the agent cannot hear you.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "End call" }));
    expect(await screen.findByText("Call ended")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Call again" })).toBeInTheDocument();
    expect(onEnded).toHaveBeenCalledTimes(1);
    expect(onEnded.mock.calls[0]![0]).toMatchObject({ reason: "user_hangup", callId: expect.stringMatching(/^call_/) });
    // The transcript stays for review after the call.
    expect(within(screen.getByRole("list", { name: "Transcript" })).getByText("Thursday at 2:15 works.")).toBeInTheDocument();
  });

  it("stops at a blocked microphone: no session request, explains how to allow it", async () => {
    const user = userEvent.setup();
    const { driver, calls } = spy(createMockDriver({ ...FAST, microphone: "denied" }));
    renderPanel({ driver });
    await user.click(screen.getByRole("button", { name: "Start test call" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Microphone access is blocked");
    expect(alert).toHaveTextContent("nothing was charged");
    expect(calls).toEqual(["mic"]);
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("reports a missing microphone", async () => {
    const user = userEvent.setup();
    renderPanel({ mockOptions: { ...FAST, microphone: "unavailable" } });
    await user.click(screen.getByRole("button", { name: "Start test call" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("No microphone found");
  });

  it("shows a credit refusal with a link to add funds", async () => {
    const user = userEvent.setup();
    renderPanel({ mockOptions: { ...FAST, refuseWith: 402 } });
    await user.click(screen.getByRole("button", { name: "Start test call" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Not enough credit");
    expect(within(alert).getByRole("link", { name: "Add funds" })).toHaveAttribute("href", "/billing");
  });

  it("shows the server's words for a concurrency refusal", async () => {
    const user = userEvent.setup();
    renderPanel({ mockOptions: { ...FAST, refuseWith: 429 } });
    await user.click(screen.getByRole("button", { name: "Start test call" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/5 calls at once/);
  });

  it("shows a connection failure and lets the operator retry", async () => {
    const user = userEvent.setup();
    renderPanel({ mockOptions: { ...FAST, failConnect: true } });
    await user.click(screen.getByRole("button", { name: "Start test call" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not join the call");
    expect(screen.getByText("Call not started")).toBeInTheDocument();
  });

  it("cancels while connecting and hangs up the late connection", async () => {
    const user = userEvent.setup();
    const hangUp = vi.fn(async () => {});
    let release: () => void = () => {};
    const inner = createMockDriver(FAST);
    const driver: WebCallDriver = {
      ...inner,
      connect: () =>
        new Promise((resolve) => {
          release = () => resolve({ setMuted: async () => {}, hangUp });
        }),
    };
    renderPanel({ driver });
    await user.click(screen.getByRole("button", { name: "Start test call" }));
    await user.click(await screen.findByRole("button", { name: "Cancel" }));
    expect(screen.getByRole("button", { name: "Start test call" })).toBeInTheDocument();
    release();
    await waitFor(() => expect(hangUp).toHaveBeenCalled());
    expect(screen.queryByText("On air")).not.toBeInTheDocument();
  });

  it("hangs up when the panel unmounts mid-call", async () => {
    const user = userEvent.setup();
    const hangUp = vi.fn(async () => {});
    const inner = createMockDriver(FAST);
    const driver: WebCallDriver = { ...inner, connect: async () => ({ setMuted: async () => {}, hangUp }) };
    const { unmount } = renderPanel({ driver });
    await user.click(screen.getByRole("button", { name: "Start test call" }));
    await screen.findByText("On air");
    unmount();
    expect(hangUp).toHaveBeenCalled();
  });

  it("does not label a live panel as simulated", () => {
    render(
      <MemoryRouter>
        <TooltipProvider>
          <WebCallPanel agentId={AGENT} mode="live" />
        </TooltipProvider>
      </MemoryRouter>,
    );
    expect(screen.queryByText("Simulated")).not.toBeInTheDocument();
  });
});

describe("live driver", () => {
  it("never requests a session when the microphone is blocked", async () => {
    const user = userEvent.setup();
    const sessionRequest = vi.fn();
    server.use(
      http.post(`${env.apiBaseUrl}/sessions/web-call`, () => {
        sessionRequest();
        return HttpResponse.json({}, { status: 500 });
      }),
    );
    const err = new DOMException("Permission denied", "NotAllowedError");
    vi.stubGlobal("navigator", { ...navigator, mediaDevices: { getUserMedia: vi.fn().mockRejectedValue(err) } });
    renderPanel({ mode: "live", mockOptions: undefined });
    await user.click(screen.getByRole("button", { name: "Start test call" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Microphone access is blocked");
    expect(sessionRequest).not.toHaveBeenCalled();
  });

  it("checks the microphone: granted stops the probe stream, denied and missing are told apart", async () => {
    const stop = vi.fn();
    vi.stubGlobal("navigator", {
      ...navigator,
      mediaDevices: { getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [{ stop }] }) },
    });
    expect(await checkMicrophone()).toBe("granted");
    expect(stop).toHaveBeenCalled();

    vi.stubGlobal("navigator", {
      ...navigator,
      mediaDevices: { getUserMedia: vi.fn().mockRejectedValue(new DOMException("none", "NotFoundError")) },
    });
    expect(await checkMicrophone()).toBe("unavailable");

    vi.stubGlobal("navigator", {
      ...navigator,
      permissions: { query: vi.fn().mockResolvedValue({ state: "denied" }) },
      mediaDevices: { getUserMedia: vi.fn() },
    });
    expect(await checkMicrophone()).toBe("denied");

    vi.stubGlobal("navigator", { ...navigator, mediaDevices: undefined });
    expect(await checkMicrophone()).toBe("unavailable");
  });

  it("requests the session with an idempotency key and the draft version by default", async () => {
    let seen: { key: string | null; body: unknown } | null = null;
    server.use(
      http.post(`${env.apiBaseUrl}/sessions/web-call`, async ({ request }) => {
        seen = { key: request.headers.get("Idempotency-Key"), body: await request.json() };
        return HttpResponse.json(
          {
            call_id: "call_01JABCDEF0123456789ABCDEFG",
            agent_version_id: "agv_01JABCDEF0123456789ABCDEFG",
            room_name: "call-x",
            server_url: "wss://lk.example",
            participant_token: "t",
            expires_at: new Date().toISOString(),
            status: "queued",
          },
          { status: 201 },
        );
      }),
    );
    const s = await createLiveDriver().createSession({ agent_id: AGENT, dynamic_variables: { customer_name: "Priya" } }, "key-12345678");
    expect(s.call_id).toBe("call_01JABCDEF0123456789ABCDEFG");
    expect(seen).toEqual({ key: "key-12345678", body: { agent_id: AGENT, version: "draft", dynamic_variables: { customer_name: "Priya" } } });
  });
});
