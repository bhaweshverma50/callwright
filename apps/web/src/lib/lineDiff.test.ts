import { describe, expect, it } from "vitest";
import { diffStats, lineDiff } from "./lineDiff";

describe("lineDiff", () => {
  it("keeps common lines and marks additions and removals", () => {
    const lines = lineDiff("a\nb\nc", "a\nB\nc\nd");
    expect(lines).toEqual([
      { kind: "same", text: "a" },
      { kind: "remove", text: "b" },
      { kind: "add", text: "B" },
      { kind: "same", text: "c" },
      { kind: "add", text: "d" },
    ]);
    expect(diffStats(lines)).toEqual({ added: 2, removed: 1 });
  });

  it("falls back to before then after for texts too long to compare line by line", () => {
    const before = Array.from({ length: 2100 }, (_, i) => `b${i}`).join("\n");
    const after = Array.from({ length: 2100 }, (_, i) => `a${i}`).join("\n");
    const lines = lineDiff(before, after);
    expect(diffStats(lines)).toEqual({ added: 2100, removed: 2100 });
    expect(lines[0]).toEqual({ kind: "remove", text: "b0" });
    expect(lines[2100]).toEqual({ kind: "add", text: "a0" });
  });
});
