import { describe, expect, it } from "vitest";
import { initialTour, persisted, tourReducer, type TourEvent, type TourState } from "./machine";
import { COUNTED, STEPS, agentInPath, onStepPage, stepIndex, stepPath } from "./steps";

const run = (events: TourEvent[], from: TourState = initialTour) => events.reduce(tourReducer, from);
const loaded = (status: TourState["status"] = "not_started", step: string | null = null) => run([{ type: "load", status, step }]);

describe("tour state machine (013)", () => {
  it("loads saved progress once; a tour in progress comes back paused at its step", () => {
    const s = loaded("in_progress", "publish");
    expect(s).toMatchObject({ phase: "paused", status: "in_progress", index: stepIndex("publish"), loaded: true });
    // A second load (a refetch) never moves the user.
    expect(tourReducer(s, { type: "load", status: "skipped", step: null })).toBe(s);
    expect(loaded("completed", "done").phase).toBe("idle");
    expect(loaded("in_progress", "no-such-step").index).toBe(0);
  });

  it("offers the welcome only to a loaded user who has not started", () => {
    expect(tourReducer(initialTour, { type: "offer" }).phase).toBe("idle");
    expect(tourReducer(loaded(), { type: "offer" }).phase).toBe("offer");
    expect(tourReducer(loaded("skipped", "agents"), { type: "offer" }).phase).toBe("idle");
    expect(tourReducer(loaded("completed", "done"), { type: "offer" }).phase).toBe("idle");
  });

  it("skip for now records skipped and closes the welcome", () => {
    const s = run([{ type: "offer" }, { type: "decline" }], loaded());
    expect(s).toMatchObject({ status: "skipped", phase: "idle" });
    expect(persisted(s)).toEqual({ status: "skipped", step: "agents" });
  });

  it("follows along: start, next, back, finish after the recap", () => {
    let s = run([{ type: "offer" }, { type: "start" }], loaded());
    expect(s).toMatchObject({ status: "in_progress", phase: "running", index: 0 });
    expect(persisted(s)).toEqual({ status: "in_progress", step: "agents" });
    s = run([{ type: "next" }, { type: "next" }, { type: "back" }], s);
    expect(STEPS[s.index]!.id).toBe("template");
    s = run([{ type: "back" }, { type: "back" }], s);
    expect(s.index).toBe(0);
    s = run(
      Array.from({ length: COUNTED }, () => ({ type: "next" }) as const),
      s,
    );
    expect(STEPS[s.index]!.id).toBe("done");
    s = tourReducer(s, { type: "next" });
    expect(s).toMatchObject({ status: "completed", phase: "idle" });
    expect(persisted(s)).toEqual({ status: "completed", step: "done" });
  });

  it("pauses and resumes at the same step without changing what is saved", () => {
    const running = run([{ type: "start" }, { type: "next" }, { type: "next" }], loaded());
    const paused = tourReducer(running, { type: "pause" });
    expect(paused.phase).toBe("paused");
    expect(persisted(paused)).toEqual(persisted(running));
    expect(tourReducer(paused, { type: "next" })).toBe(paused);
    expect(tourReducer(paused, { type: "resume" })).toMatchObject({ phase: "running", index: running.index });
  });

  it("skips from any step, running or paused, and keeps the step it was on", () => {
    const at = run([{ type: "start" }, { type: "goto", step: "test-call" }], loaded());
    expect(persisted(tourReducer(at, { type: "skip" }))).toEqual({ status: "skipped", step: "test-call" });
    expect(tourReducer(tourReducer(at, { type: "pause" }), { type: "skip" }).status).toBe("skipped");
  });

  it("restarts from the first step after skipping or completing", () => {
    for (const status of ["skipped", "completed"] as const) {
      const s = tourReducer(loaded(status, "voice"), { type: "start" });
      expect(s).toMatchObject({ status: "in_progress", phase: "running", index: 0 });
    }
  });

  it("ignores moves while nothing runs", () => {
    const idle = loaded("skipped", "voice");
    for (const type of ["next", "back", "pause", "resume", "finish", "decline"] as const) expect(tourReducer(idle, { type })).toBe(idle);
  });
});

describe("tour steps", () => {
  it("has unique ids that fit the server's step pattern", () => {
    const ids = STEPS.map((s) => s.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const id of ids) expect(id).toMatch(/^[a-z][a-z0-9_-]{0,39}$/);
    expect(ids.at(-1)).toBe("done");
  });

  it("fills in the agent, and needs one for agent pages", () => {
    const prompt = STEPS[stepIndex("prompt")]!;
    expect(stepPath(prompt, null)).toBeNull();
    expect(stepPath(prompt, "agt_X")).toBe("/agents/agt_X/edit");
    expect(onStepPage(prompt, "/agents/agt_X/edit", { pathname: "/agents/agt_X/edit", search: "?tab=voice" })).toBe(false);
    const voice = STEPS[stepIndex("voice")]!;
    expect(onStepPage(voice, "/agents/agt_X/edit", { pathname: "/agents/agt_X/edit", search: "?tab=voice" })).toBe(true);
  });

  it("reads the agent from agent page addresses only", () => {
    const id = "agt_01M6G9S4QHATK1HNR5XR81TG0N";
    expect(agentInPath(`/agents/${id}/edit`)).toBe(id);
    expect(agentInPath(`/agents/${id}/testing`)).toBe(id);
    expect(agentInPath(`/agents/${id}/flow`)).toBeNull();
    expect(agentInPath("/agents/templates")).toBeNull();
  });

  it("the agents step is done once the templates or a new agent page opens", () => {
    const step = STEPS[0]!;
    const env = (pathname: string) => ({ pathname, search: "", doc: document });
    expect(step.doneWhen!(env("/agents"))).toBe(false);
    expect(step.doneWhen!(env("/agents/templates"))).toBe(true);
    expect(step.doneWhen!(env("/agents/new"))).toBe(true);
  });
});
