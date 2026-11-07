import { describe, expect, it } from "vitest";
import { e164Error } from "./e164";

describe("e164Error", () => {
  it("accepts a plus, a country code and 7 to 15 digits", () => {
    expect(e164Error("+14155550100")).toBeNull();
    expect(e164Error(" +442071838750 ")).toBeNull();
  });

  it("says what is wrong", () => {
    expect(e164Error("", "destination number")).toBe("Enter the destination number.");
    expect(e164Error(undefined)).toBe("Enter the number.");
    expect(e164Error("14155550100")).toMatch(/Start with \+ and the country code/);
    expect(e164Error("+1 415 555 0100")).toMatch(/Digits only/);
    expect(e164Error("+12345")).toMatch(/7 to 15 digits/);
  });
});
