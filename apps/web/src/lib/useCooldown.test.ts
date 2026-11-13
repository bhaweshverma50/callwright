import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { mmss, useCooldown } from "./useCooldown";

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

it("counts down after a restart and frees the button at zero", () => {
  const { result } = renderHook(() => useCooldown(60));
  expect(result.current.left).toBe(0);
  act(() => result.current.restart());
  expect(result.current.left).toBe(60);
  act(() => void vi.advanceTimersByTime(59_000));
  expect(result.current.left).toBe(1);
  act(() => void vi.advanceTimersByTime(1_000));
  expect(result.current.left).toBe(0);
});

it("formats minutes and seconds", () => {
  expect(mmss(60)).toBe("1:00");
  expect(mmss(5)).toBe("0:05");
});
