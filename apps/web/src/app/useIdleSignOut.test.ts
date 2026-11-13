import { renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { IDLE_LIMIT_MS, idleFor, startSession, touchActivity } from "../api/session";
import { useIdleSignOut } from "./useIdleSignOut";

const signOut = vi.fn(async () => {});
vi.mock("../api/auth", () => ({ signOut: () => signOut() }));

describe("useIdleSignOut", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    localStorage.clear();
    signOut.mockClear();
  });
  afterEach(() => vi.useRealTimers());

  it("signs out on mount when the last activity is older than the limit", () => {
    localStorage.setItem("cw.lastActive", String(Date.now() - IDLE_LIMIT_MS - 1000));
    renderHook(() => useIdleSignOut(true));
    expect(signOut).toHaveBeenCalledTimes(1);
  });

  it("signs out after the limit passes without input, not before", () => {
    renderHook(() => useIdleSignOut(true));
    vi.advanceTimersByTime(IDLE_LIMIT_MS - 60_000);
    expect(signOut).not.toHaveBeenCalled();
    vi.advanceTimersByTime(2 * 60_000);
    expect(signOut).toHaveBeenCalledTimes(1);
  });

  it("input keeps the session alive", () => {
    renderHook(() => useIdleSignOut(true));
    vi.advanceTimersByTime(IDLE_LIMIT_MS - 60_000);
    window.dispatchEvent(new Event("keydown"));
    vi.advanceTimersByTime(2 * 60_000);
    expect(signOut).not.toHaveBeenCalled();
  });

  it("a fresh sign-in resets an old activity time", () => {
    localStorage.setItem("cw.lastActive", String(Date.now() - IDLE_LIMIT_MS - 1000));
    startSession({ access_token: "a", refresh_token: "r" } as Parameters<typeof startSession>[0]);
    expect(idleFor()).toBeLessThan(1000);
    touchActivity(true);
  });

  it("does nothing while signed out", () => {
    localStorage.setItem("cw.lastActive", String(Date.now() - IDLE_LIMIT_MS - 1000));
    renderHook(() => useIdleSignOut(false));
    expect(signOut).not.toHaveBeenCalled();
  });
});
