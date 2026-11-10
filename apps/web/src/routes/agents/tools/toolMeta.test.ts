import { describe, expect, it } from "vitest";
import { DEFAULT_CONFIGS } from "./toolMeta";

describe("new tool defaults", () => {
  it("start from the contract's defaults", () => {
    expect(DEFAULT_CONFIGS.press_digit).toEqual({ delay_ms: 1000, cooldown_ms: 5000 });
    expect(DEFAULT_CONFIGS.transfer_call).toMatchObject({ routing_type: "static", transfer_type: "cold", ring_timeout_s: 30, allowed_numbers: [] });
    expect(DEFAULT_CONFIGS.http).toMatchObject({ method: "POST", timeout_ms: 8000, speak_during_execution: true, parameters: { type: "object" } });
  });
});
