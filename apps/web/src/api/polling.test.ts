/** Refresh decisions: how often each live surface polls, keyed on what is still changing. */
import { describe, expect, it } from "vitest";
import { POLL_IDLE_MS, POLL_LIVE_MS, POLL_PENDING_MS, callDetailInterval, callsListInterval, liveDetailInterval, type CallStatus } from "./calls";
import { diffLive, liveCallsInterval } from "./live";

const rows = (...s: CallStatus[]) => s.map((status) => ({ status }));

describe("call list", () => {
  it("polls fast while any row can still change and slowly otherwise", () => {
    for (const s of ["queued", "ringing", "in_progress", "ended", "processing"] as const) {
      expect(callsListInterval(rows("completed", s))).toBe(POLL_PENDING_MS);
    }
    expect(callsListInterval(rows("completed", "failed", "no_answer", "busy", "voicemail"))).toBe(POLL_IDLE_MS);
    expect(callsListInterval([])).toBe(POLL_IDLE_MS);
    expect(callsListInterval(undefined)).toBe(POLL_IDLE_MS);
  });
});

describe("call detail", () => {
  const done = { processing_state: "done" as const, recording_pending: false };
  it("is fastest while ringing or live", () => {
    for (const s of ["queued", "ringing", "in_progress"] as const) expect(callDetailInterval({ ...done, status: s })).toBe(POLL_LIVE_MS);
  });
  it("keeps polling while analysis or the recording finish, then stops", () => {
    expect(callDetailInterval({ status: "processing", processing_state: "pending", recording_pending: false })).toBe(POLL_PENDING_MS);
    expect(callDetailInterval({ status: "completed", processing_state: "done", recording_pending: true })).toBe(POLL_PENDING_MS);
    expect(callDetailInterval({ ...done, status: "completed" })).toBe(false);
    expect(callDetailInterval({ ...done, status: "failed" })).toBe(false);
    expect(callDetailInterval(undefined)).toBe(false);
  });
  it("refreshes transcript, latencies and flow path only during the call", () => {
    expect(liveDetailInterval(true)).toBe(POLL_LIVE_MS);
    expect(liveDetailInterval(false)).toBe(false);
  });
});

describe("calls on air", () => {
  it("polls every few seconds while a call is on air and slowly when none is", () => {
    expect(liveCallsInterval({ count: 2 })).toBe(POLL_LIVE_MS);
    expect(liveCallsInterval({ count: 0 })).toBe(POLL_IDLE_MS);
    expect(liveCallsInterval(undefined)).toBe(POLL_IDLE_MS);
  });

  it("reports calls that started, connected and ended between polls", () => {
    expect(diffLive(null, [{ call_id: "a", status: "ringing" }])).toEqual({ started: [], connected: [], ended: [] });
    const prev = new Map([
      ["a", "ringing"],
      ["b", "in_progress"],
    ]);
    expect(
      diffLive(prev, [
        { call_id: "a", status: "in_progress" },
        { call_id: "c", status: "ringing" },
      ]),
    ).toEqual({ started: ["c"], connected: ["a"], ended: ["b"] });
    expect(
      diffLive(prev, [
        { call_id: "a", status: "ringing" },
        { call_id: "b", status: "in_progress" },
      ]),
    ).toEqual({
      started: [],
      connected: [],
      ended: [],
    });
  });
});
