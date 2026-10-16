import { describe, expect, it, vi } from "vitest";
import { configureWake, resetWake, wakeAwareFetch, wakeStore, type WakeState } from "./wakeGate";

const waking = () =>
  new Response(JSON.stringify({ type: "x", title: "Starting", status: 503, code: "waking_up" }), {
    status: 503,
    headers: { "content-type": "application/problem+json", "retry-after": "45" },
  });
const ok = (body = "ok") => new Response(JSON.stringify({ body }), { status: 200 });

/** A fake clock that moves only when the gate sleeps, so no test waits for real time. */
function fakeTime() {
  let t = 0;
  configureWake({
    now: () => t,
    sleep: async (ms) => {
      t += ms;
      await Promise.resolve();
    },
  });
  return { advance: (ms: number) => (t += ms) };
}

function states() {
  const seen: WakeState["status"][] = [];
  wakeStore.subscribe(() => seen.push(wakeStore.get().status));
  return seen;
}

describe("wake gate", () => {
  it("passes ordinary responses straight through", async () => {
    const send = vi.fn().mockResolvedValue(ok());
    const res = await wakeAwareFetch(send);
    expect(res.status).toBe(200);
    expect(send).toHaveBeenCalledTimes(1);
    expect(wakeStore.get().status).toBe("idle");
  });

  it("retries the waking request with backoff and returns its first real answer", async () => {
    fakeTime();
    const seen = states();
    const send = vi
      .fn()
      .mockResolvedValueOnce(waking())
      .mockResolvedValueOnce(waking())
      .mockRejectedValueOnce(new TypeError("net"))
      .mockResolvedValueOnce(ok("done"));
    const res = await wakeAwareFetch(send);
    expect(await res.json()).toEqual({ body: "done" });
    expect(send).toHaveBeenCalledTimes(4);
    expect(seen[0]).toBe("waking");
    expect(wakeStore.get().status).toBe("idle");
  });

  it("queues other requests behind the gate and sends them once the servers answer", async () => {
    let release!: () => void;
    const released = new Promise<void>((r) => (release = r));
    configureWake({ sleep: () => released });
    const lead = vi.fn().mockResolvedValueOnce(waking()).mockResolvedValueOnce(ok("lead"));
    const leader = wakeAwareFetch(lead);
    await vi.waitFor(() => expect(wakeStore.get().status).toBe("waking"));

    const later = vi.fn().mockResolvedValue(ok("later"));
    const follower = wakeAwareFetch(later);
    const inflight = vi.fn().mockResolvedValueOnce(waking()).mockResolvedValueOnce(ok("inflight"));
    const joined = wakeAwareFetch(inflight);
    await Promise.resolve();
    expect(later).not.toHaveBeenCalled();

    release();
    expect(await (await leader).json()).toEqual({ body: "lead" });
    expect(await (await follower).json()).toEqual({ body: "later" });
    expect(await (await joined).json()).toEqual({ body: "inflight" });
    expect(later).toHaveBeenCalledTimes(1);
    expect(lead).toHaveBeenCalledTimes(2);
  });

  it("gives up after about three minutes, then Retry lets requests try again", async () => {
    fakeTime();
    const send = vi.fn().mockImplementation(async () => waking());
    const res = await wakeAwareFetch(send);
    expect(res.status).toBe(503);
    expect(wakeStore.get().status).toBe("failed");
    const attempts = send.mock.calls.length;
    expect(attempts).toBeGreaterThan(5);

    // While failed, new requests fail fast instead of opening another wait.
    expect((await wakeAwareFetch(send)).status).toBe(503);
    expect(send.mock.calls.length).toBe(attempts + 1);

    resetWake();
    expect(wakeStore.get().status).toBe("idle");
    send.mockResolvedValueOnce(ok("back"));
    expect(await (await wakeAwareFetch(send)).json()).toEqual({ body: "back" });
  });

  it("ignores other 503s", async () => {
    const other = new Response(JSON.stringify({ code: "auth_unavailable" }), { status: 503 });
    const send = vi.fn().mockResolvedValue(other);
    expect((await wakeAwareFetch(send)).status).toBe(503);
    expect(send).toHaveBeenCalledTimes(1);
    expect(wakeStore.get().status).toBe("idle");
  });
});
