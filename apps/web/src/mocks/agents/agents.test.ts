import { describe, expect, it } from "vitest";
import { api, unwrap } from "../../api/client";
import { looseConfig, type AgentConfig, type AgentDetail, type SaveResult } from "../../api/agents";
import { signInDemo } from "../../test/render";
import { diffConfigs } from "./diff";
import { defaultConfig, validateConfig } from "./rules";

describe("mock agent rules (002 data-model sections 4 and 5)", () => {
  it("lists every blocking problem in one pass (US1.5, SC-004)", () => {
    const c = defaultConfig("single_prompt");
    c.tts.voice_id = "";
    c.advanced.webhook_url = "ftp://x";
    const r = validateConfig("single_prompt", c);
    expect(r.valid).toBe(false);
    expect(r.errors.map((e) => e.pointer).sort()).toEqual(["/advanced/webhook_url", "/prompt", "/tts/voice_id"]);
  });

  it("applies fixed temperatures and drops empty pronunciation rows", () => {
    const c = defaultConfig("single_prompt");
    c.prompt = "Hi";
    c.llm.temperature = 0.4;
    c.advanced.pronunciation = [
      { word: "", replacement: "" },
      { word: "SQL", replacement: "sequel" },
    ];
    const r = validateConfig("single_prompt", c);
    expect(r.normalized_config.llm.temperature).toBe(1);
    expect(r.warnings.some((w) => w.code === "temperature_fixed")).toBe(true);
    expect(r.normalized_config.advanced.pronunciation).toHaveLength(1);
  });

  it("refuses private webhook hosts and out-of-range call behaviour", () => {
    const c = defaultConfig("single_prompt");
    c.prompt = "Hi";
    c.advanced.webhook_url = "https://192.168.1.4/hook";
    c.call_behavior.max_duration_s = 12;
    c.call_behavior.ring_duration_ms = -1000;
    c.advanced.webhook_timeout_ms = 50;
    const codes = validateConfig("single_prompt", c).errors.map((e) => `${e.pointer}:${e.code}`);
    expect(codes).toEqual(
      expect.arrayContaining([
        "/advanced/webhook_url:private_address",
        "/call_behavior/max_duration_s:out_of_range",
        "/call_behavior/ring_duration_ms:out_of_range",
        "/advanced/webhook_timeout_ms:out_of_range",
      ]),
    );
  });

  it("diffs keyed lists by key, not position", () => {
    const a = defaultConfig("single_prompt");
    a.dynamic_variables = [
      { name: "a", default: "1" },
      { name: "b", default: "2" },
    ];
    const b = structuredClone(a) as AgentConfig;
    b.dynamic_variables = [
      { name: "b", default: "3" },
      { name: "a", default: "1" },
    ];
    b.tts.speed = 1.2;
    expect(diffConfigs(a, b)).toEqual([
      { op: "replace", path: "/dynamic_variables[b]/default", old: "2", new: "3" },
      { op: "replace", path: "/tts/speed", old: 1, new: 1.2 },
    ]);
  });
});

describe("mock agents API", () => {
  it("creates once per idempotency key, saves versions only on change, and refuses stale saves", async () => {
    await signInDemo();
    const config = defaultConfig("single_prompt");
    config.prompt = "Hello {{customer_name}}.";
    const body = { name: "Desk", type: "single_prompt" as const, config: looseConfig(config) };
    const params = { header: { "Idempotency-Key": "k1" } };
    const a = (await unwrap(api.POST("/agents", { body, params }))) as AgentDetail;
    const b = (await unwrap(api.POST("/agents", { body, params }))) as AgentDetail;
    expect(b.id).toBe(a.id);
    expect(a.draft_version.version_number).toBe(1);

    const put = (rev: number, cfg: AgentConfig) =>
      api.PUT("/agents/{agent_id}/draft", { params: { path: { agent_id: a.id }, header: { "If-Match": `"${rev}"` } }, body: { config: cfg } });
    const same = (await unwrap(put(a.draft_revision, a.draft_config))) as SaveResult;
    expect(same.created).toBe(false);
    const changed = (await unwrap(put(same.agent.draft_revision, { ...a.draft_config, prompt: "Changed" }))) as SaveResult;
    expect(changed.version.version_number).toBe(2);
    const stale = await put(a.draft_revision, a.draft_config);
    expect(stale.response.status).toBe(412);
  });
});
