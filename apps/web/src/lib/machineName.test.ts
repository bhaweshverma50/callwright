import { describe, expect, it } from "vitest";
import { FLOW_FIELD_NAME_MAX, isMachineName, toMachineName } from "./machineName";

describe("toMachineName (007 FR-045, 004 FR-056)", () => {
  it.each([
    ["Customer Mood", "customer_mood"],
    ["  Preferred   day!! ", "preferred_day"],
    [" 2nd Phone! ", "v_2nd_phone"],
    ["__x__", "x"],
    ["Café visit", "cafe_visit"],
    ["!!!", ""],
  ])("%s becomes %s", (input, expected) => {
    expect(toMachineName(input)).toBe(expected);
  });

  it("keeps at most the allowed length", () => {
    expect(toMachineName("a".repeat(80))).toHaveLength(64);
    expect(toMachineName("a".repeat(80), FLOW_FIELD_NAME_MAX)).toHaveLength(40);
  });

  it("accepts only lowercase names that start with a letter", () => {
    expect(isMachineName("order_id")).toBe(true);
    expect(isMachineName("Order")).toBe(false);
    expect(isMachineName("1st")).toBe(false);
    expect(isMachineName("a".repeat(41), FLOW_FIELD_NAME_MAX)).toBe(false);
  });
});
