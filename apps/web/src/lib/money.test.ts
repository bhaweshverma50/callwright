import { describe, expect, it } from "vitest";
import { checkTopUpAmount, formatCentsPerMin, formatUsd, toMicros } from "./money";

describe("money formatting", () => {
  it("formats balances to three decimals", () => {
    expect(formatUsd("5.000000", { places: 3 })).toBe("$5.000");
    expect(formatUsd("1234.5", { places: 2 })).toBe("$1,234.50");
    expect(formatUsd("-0.477000", { places: 3 })).toBe("-$0.477");
    expect(formatUsd("25", { places: 3, signed: true })).toBe("+$25.000");
  });
  it("parses decimal strings exactly", () => {
    expect(toMicros("0.0085")).toBe(8500n);
    expect(toMicros("abc")).toBeNull();
  });
  it("shows rates as cents per minute", () => {
    expect(formatCentsPerMin("0.0085")).toBe("0.85¢");
    expect(formatCentsPerMin("0.0450")).toBe("4.50¢");
    expect(formatCentsPerMin("0.0000")).toBe("0.00¢");
  });
});

describe("top-up amount rules (US2.5, FR-008)", () => {
  it.each([
    ["4", "minimum"],
    ["0", "minimum"],
    ["10001", "maximum"],
    ["10000.01", "maximum"],
    ["5.555", "two digits"],
    ["", "between"],
    ["ten", "numbers only"],
  ])("rejects %s", (input, reason) => {
    const r = checkTopUpAmount(input);
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason.toLowerCase()).toContain(reason);
  });
  it.each([
    ["5", "5.00"],
    ["$100", "100.00"],
    ["10,000", "10000.00"],
    ["99.5", "99.50"],
  ])("accepts %s", (input, normalized) => {
    const r = checkTopUpAmount(input);
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.normalized).toBe(normalized);
  });
});
