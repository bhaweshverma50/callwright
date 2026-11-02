import { describe, expect, it } from "vitest";
import { withoutLineRefs } from "./text";

describe("withoutLineRefs", () => {
  it("drops single, range and list references and keeps the rest", () => {
    expect(withoutLineRefs('Paid: "Oh, yes. I made the payment." [12]; confirmed [8, 10-11].')).toBe(
      'Paid: "Oh, yes. I made the payment."; confirmed.',
    );
    expect(withoutLineRefs(null)).toBeNull();
  });
});
