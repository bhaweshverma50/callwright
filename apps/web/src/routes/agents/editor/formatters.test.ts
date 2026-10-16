import { describe, expect, it } from "vitest";
import { formatControl, formatMs, formatMultiplier, formatPercentOfNormal, formatSeconds, parseNumber, snap } from "./formatters";
import { surchargeRisk } from "./surchargeRisk";

describe("formatters (T094, FR-042)", () => {
  it("reads durations exactly", () => {
    expect(formatMs(1500)).toBe("1.5 s");
    expect(formatMs(5000)).toBe("5 s");
    expect(formatSeconds(30)).toBe("30 s");
    expect(formatSeconds(90)).toBe("1 min 30 s");
    expect(formatSeconds(600)).toBe("10 min");
    expect(formatSeconds(12)).toBe("12 s");
  });

  it("shows volumes as percent of normal and speed as a multiplier", () => {
    expect(formatPercentOfNormal(1)).toBe("100%");
    expect(formatPercentOfNormal(0.8)).toBe("80%");
    expect(formatPercentOfNormal(3)).toBe("300%");
    expect(formatMultiplier(1)).toBe("1.0x");
    expect(formatMultiplier(1.25)).toBe("1.25x");
  });

  it("labels equal stored values for the catalog defaults (US1.14)", () => {
    expect(formatControl({ display: "decimal", unit: null }, 0.8)).toBe("0.80");
    expect(formatControl({ display: "percent_of_normal", unit: null }, 1)).toBe("100%");
    expect(formatControl({ display: "duration", unit: "ms" }, 1500)).toBe("1.5 s");
  });

  it("snaps to the step without float noise and parses typed numbers", () => {
    expect(snap(0.94, 0, 0.05)).toBe(0.95);
    expect(snap(0.30000000000000004, 0, 0.1)).toBe(0.3);
    expect(parseNumber(" 2.5 ")).toBe(2.5);
    expect(parseNumber("-1")).toBe(-1);
    expect(parseNumber("abc")).toBeNull();
    expect(parseNumber("")).toBeNull();
  });
});

describe("surcharge risk (T064)", () => {
  const words = (n: number) => Array.from({ length: n }, () => "word").join(" ");
  it("flags about 3,300 words against a 20,000 token bundle", () => {
    expect(surchargeRisk(words(3300), 20_000)?.risk).toBe(true);
  });
  it("does not flag 1,000 words", () => {
    expect(surchargeRisk(words(1000), 20_000)?.risk).toBe(false);
  });
  it("needs a bundle from the quote", () => {
    expect(surchargeRisk(words(5000), null)).toBeNull();
  });
});
