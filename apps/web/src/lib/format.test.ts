import { describe, expect, it } from "vitest";
import { costUsd, mss, pct, pp, shortId, timeAgo, usd } from "./format";

describe("display formatting", () => {
  it("formats rates and percentage points, rounding half away from zero (008 FR-021, SC-003)", () => {
    expect(pct(0.4)).toBe("40%");
    expect(pct(0.405)).toBe("40.5%");
    expect(pct(0.405, 0)).toBe("41%");
    expect(pct(null)).toBe("n/a");
    expect(pp(30)).toBe("+30.0 pp");
    expect(pp(-0.05)).toBe("-0.1 pp");
    expect(pp(0.04)).toBe("0.0 pp");
    expect(pp(null)).toBe("n/a");
  });

  it("says how long ago, then falls back to the date", () => {
    const now = Date.parse("2026-10-20T12:00:00Z");
    expect(timeAgo("2026-10-20T11:59:30Z", now)).toBe("just now");
    expect(timeAgo("2026-10-20T11:55:00Z", now)).toBe("5 min ago");
    expect(timeAgo("2026-10-20T09:00:00Z", now)).toBe("3 h ago");
    expect(timeAgo("2026-10-19T12:00:00Z", now)).toBe("1 day ago");
    expect(timeAgo("2026-10-10T12:00:00Z", now)).toBe("10 days ago");
    expect(timeAgo("2026-08-01T12:00:00Z", now)).not.toMatch(/ago/);
    expect(timeAgo(null, now)).toBe("");
  });

  it("prints dollars from JSON numbers through the money formatter", () => {
    expect(usd(0.477)).toBe("$0.477");
    expect(usd(1234.5, 2)).toBe("$1,234.50");
    expect(costUsd(0.0123)).toBe("$0.0123");
    expect(costUsd(12.3)).toBe("$12.30");
    expect(costUsd(null)).toBe("n/a");
  });

  it("prints durations and keeps both ends of long ids", () => {
    expect(mss(271)).toBe("4:31");
    expect(mss(3725)).toBe("1:02:05");
    expect(shortId("call_01MOCKSIMCALL0000000000007")).toBe("call_01MO...000007");
  });
});
