import { describe, expect, it } from "vitest";
import { priceQuote, type CatalogLike } from "./engine";

const catalog: CatalogLike = {
  version: 1,
  entries: [
    { component: "stt", provider: "deepgram", model: "nova-3", label: "Nova-3", rate_per_min_usd: "0.0085", bundles: [] },
    { component: "stt", provider: "deepgram", model: null, label: "Deepgram, Auto", rate_per_min_usd: "0.0085", bundles: [] },
    {
      component: "llm",
      provider: "azure_openai",
      model: "gpt-5-mini",
      label: "GPT-5 Mini",
      rate_per_min_usd: "0.0015",
      bundles: [
        { unit: "llm_input_tokens", per_min: 20000 },
        { unit: "llm_output_tokens", per_min: 200 },
      ],
    },
    {
      component: "tts",
      provider: "elevenlabs",
      model: "eleven_flash_v2_5",
      label: "Flash v2.5",
      rate_per_min_usd: "0.0450",
      bundles: [{ unit: "tts_chars", per_min: 750 }],
    },
    { component: "nc", provider: "sanas", model: "vi", label: "Voice isolation", rate_per_min_usd: "0.0000", bundles: [] },
    { component: "platform", provider: "callwright", model: null, label: "Platform fee", rate_per_min_usd: "0.0500", bundles: [] },
  ],
};

const reference = {
  stt: { provider: "deepgram", model: "nova-3" },
  llm: { provider: "azure_openai", model: "gpt-5-mini" },
  tts: { provider: "elevenlabs", model: "eleven_flash_v2_5" },
  nc: null,
};

describe("pricing engine (001 US3, SC-004)", () => {
  it("prices the reference call to $0.477 with the LLM surcharge", () => {
    const q = priceQuote(catalog, reference, {
      duration_ms: 271_000,
      llm_input_tokens: 102_348,
      llm_output_tokens: 745,
      tts_chars: 2_555,
    });
    const call = q.call!;
    expect(call.total_usd).toBe("0.477000");
    expect(call.billed_seconds).toBe(271);
    expect(call.duration_minutes).toBe("4.516667");
    const by = Object.fromEntries(call.lines.map((l) => [l.component, l]));
    expect(by.stt!.cost_usd).toBe("0.039000");
    expect(by.llm!.cost_usd).toBe("0.008000");
    expect(by.llm!.billed_minutes).toBe("5.117400");
    expect(by.llm!.surcharge_usd).toBe("0.000901");
    expect(by.llm!.bundle_multiplier).toBe("1.1330");
    expect(by.tts!.cost_usd).toBe("0.204000");
    expect(by.tts!.surcharge_usd).toBe("0.000000");
    expect(by.tts!.bundle_multiplier).toBe("1.0000");
    expect(by.platform!.cost_usd).toBe("0.226000");
  });

  it("bills a 4.2 second call as 5 seconds", () => {
    const q = priceQuote(catalog, reference, { duration_ms: 4_200 });
    expect(q.call!.billed_seconds).toBe(5);
  });

  it("returns per-minute lines and total without usage", () => {
    const q = priceQuote(catalog, reference);
    expect(q.per_minute_total_usd).toBe("0.105000");
    expect(q.complete).toBe(true);
    expect(q.lines.map((l) => l.component)).toEqual(["stt", "llm", "tts", "platform"]);
    expect(q.call).toBeUndefined();
  });

  it("adds a noise cancellation line when selected", () => {
    const q = priceQuote(catalog, { ...reference, nc: { provider: "sanas", model: "vi" } });
    expect(q.lines.map((l) => l.component)).toContain("nc");
  });

  it("falls back to the provider row, and marks unknown vendors unpriced", () => {
    const q = priceQuote(catalog, {
      ...reference,
      stt: { provider: "deepgram", model: "nova-9" },
      tts: { provider: "not_a_vendor", model: null },
    });
    const stt = q.lines.find((l) => l.component === "stt")!;
    expect(stt.status).toBe("priced");
    expect(stt.rate_per_min_usd).toBe("0.0085");
    const tts = q.lines.find((l) => l.component === "tts")!;
    expect(tts.status).toBe("unpriced");
    expect(tts.rate_per_min_usd).toBeNull();
    expect(q.complete).toBe(false);
  });

  it("bills zero duration as zero", () => {
    const q = priceQuote(catalog, reference, { duration_ms: 0 });
    expect(q.call!.total_usd).toBe("0.000000");
  });
});
