import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ThinkingIndicator } from "./ai";

describe("thinking indicator", () => {
  afterEach(() => vi.useRealTimers());

  it("counts from when the work started, so remounting does not reset the timer", () => {
    vi.useFakeTimers();
    const started = Date.now() - 42_000;
    const { unmount } = render(<ThinkingIndicator label="Analysing" verbs={["Reading"]} since={new Date(started).toISOString()} />);
    act(() => vi.advanceTimersByTime(1000));
    expect(screen.getByText("43s")).toBeInTheDocument();
    unmount();
    render(<ThinkingIndicator label="Analysing" verbs={["Reading"]} since={new Date(started).toISOString()} />);
    act(() => vi.advanceTimersByTime(1000));
    expect(screen.getByText("44s")).toBeInTheDocument();
  });
});
