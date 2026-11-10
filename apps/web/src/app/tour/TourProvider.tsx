import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useReducer, useRef, useState, type ReactNode } from "react";
import { useLocation, useNavigate } from "react-router";
import { createAgentFromTemplate, firstTemplate, newestAgentId, useAgents } from "../../api/agents";
import { useSaveOnboarding, usePreferences } from "../../api/preferences";
import { problemMessage } from "../../api/problems";
import { toast } from "../../components";
import { TourContext, type TourApi } from "./context";
import { initialTour, persisted, tourReducer } from "./machine";
import { ResumeChip } from "./ResumeChip";
import { COUNTED, STEPS, agentInPath, onStepPage, stepPath } from "./steps";
import { TourOverlay, type StepProgress } from "./TourOverlay";
import { WelcomeCard } from "./WelcomeCard";
import { idempotencyKey } from "../../lib/idempotency";
import { agentEditPath } from "../../lib/paths";

const AGENT_KEY = "cw.tour.agent";
/** Pause after the real action before moving on, so the user sees what they did land. */
const ADVANCE_DELAY_MS = 450;

function readAgent(): string | null {
  try {
    return sessionStorage.getItem(AGENT_KEY);
  } catch {
    return null;
  }
}
function writeAgent(id: string | null) {
  try {
    if (id) sessionStorage.setItem(AGENT_KEY, id);
    else sessionStorage.removeItem(AGENT_KEY);
  } catch {
    /* the tour falls back to the newest agent */
  }
}

/**
 * The guided setup tour (spec 013), mounted once in the shell. It reads the saved progress, offers
 * the welcome card to a new user (no agents yet, never started), saves every status and step
 * change, drives the route for each step and moves on when the user does the step's real action.
 */
export function TourProvider({ children }: { children: ReactNode }) {
  const prefs = usePreferences();
  // Only someone who never started needs the agent count (the welcome is for empty workspaces).
  const agents = useAgents("", null, 1, { enabled: prefs.data?.onboarding.status === "not_started" });
  const save = useSaveOnboarding();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const loc = useLocation();
  const [state, dispatch] = useReducer(tourReducer, initialTour);
  const [agentId, setAgentId] = useState<string | null>(readAgent);
  const [announcement, setAnnouncement] = useState("");
  const running = state.phase === "running";
  const step = STEPS[state.index]!;

  // Saved progress, once.
  useEffect(() => {
    if (prefs.data) dispatch({ type: "load", status: prefs.data.onboarding.status, step: prefs.data.onboarding.step });
  }, [prefs.data]);

  // The welcome card: once, for someone who has never started or skipped and has no agent yet.
  const offered = useRef(false);
  const noAgents = agents.data?.total === 0;
  useEffect(() => {
    if (offered.current || !state.loaded || state.status !== "not_started" || !noAgents) return;
    offered.current = true;
    dispatch({ type: "offer" });
  }, [state.loaded, state.status, noAgents]);

  // Save the status and step whenever they change (pausing keeps both, so it saves nothing).
  const savedKey = useRef<string | null>(null);
  const { mutate } = save;
  useEffect(() => {
    if (!state.loaded) return;
    const p = persisted(state);
    const key = `${p.status}:${p.step}`;
    if (savedKey.current === null) {
      savedKey.current = key;
      return;
    }
    if (savedKey.current === key) return;
    savedKey.current = key;
    mutate(p);
  }, [state, mutate]);

  // Follow the agent the user opens while the tour runs.
  useEffect(() => {
    const id = agentInPath(loc.pathname);
    if (running && id && id !== agentId) {
      setAgentId(id);
      writeAgent(id);
    }
  }, [running, loc.pathname, agentId]);

  // A step on an agent page without an agent: take the newest one, or go back to creating one.
  useEffect(() => {
    if (!running || !step.needsAgent || agentId) return;
    let cancelled = false;
    void (async () => {
      try {
        const id = await newestAgentId();
        if (cancelled) return;
        if (id) {
          setAgentId(id);
          writeAgent(id);
        } else dispatch({ type: "goto", step: "template" });
      } catch (e) {
        console.warn("The tour could not find an agent; going back to the agents step.", e);
        if (!cancelled) dispatch({ type: "goto", step: "agents" });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [running, step, agentId]);

  // Open the step's page, once per step.
  const path = stepPath(step, agentId);
  const navigatedFor = useRef<string | null>(null);
  useEffect(() => {
    if (!running) {
      navigatedFor.current = null;
      return;
    }
    const key = `${state.index}:${path}`;
    if (path === null || navigatedFor.current === key) return;
    navigatedFor.current = key;
    if (!onStepPage(step, path, loc)) navigate(path);
  }, [running, state.index, path, step, loc, navigate]);

  // The real action: once the step's page is open, a change of `doneWhen` from false to true
  // moves on. If it was already true on arrival (going back to a step you did), Next does.
  const onPage = running && path !== null && onStepPage(step, path, loc);
  const arrived = useRef<{ index: number; baseline: boolean } | null>(null);
  const [baselineDone, setBaselineDone] = useState(false);
  const [doneNow, setDoneNow] = useState(false);
  useEffect(() => {
    if (!running) arrived.current = null;
    else if (arrived.current?.index !== state.index) arrived.current = null;
    setDoneNow(false);
    setBaselineDone(false);
  }, [running, state.index]);
  useEffect(() => {
    if (!running || !step.doneWhen) return;
    const check = () => {
      const done = step.doneWhen!({ pathname: loc.pathname, search: loc.search, doc: document });
      if (!arrived.current) {
        if (!onPage) return;
        arrived.current = { index: state.index, baseline: done };
        setBaselineDone(done);
        return;
      }
      if (done && !arrived.current.baseline) setDoneNow(true);
    };
    check();
    const mo = new MutationObserver(check);
    mo.observe(document.body, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ["data-phase", "data-published", "aria-selected"],
    });
    return () => mo.disconnect();
  }, [running, step, state.index, onPage, loc.pathname, loc.search]);
  useEffect(() => {
    if (!doneNow) return;
    const t = window.setTimeout(() => dispatch({ type: "next" }), ADVANCE_DELAY_MS);
    return () => window.clearTimeout(t);
  }, [doneNow]);

  // Announce each step to screen readers.
  useEffect(() => {
    if (running) {
      const n = state.index + 1;
      setAnnouncement(step.id === "done" ? `Guided setup complete. ${step.body}` : `Step ${n} of ${COUNTED}: ${step.title}. ${step.body}`);
    } else if (state.phase === "paused") setAnnouncement("Guided setup paused. Resume it from the chip at the bottom of the page.");
  }, [running, state.phase, state.index, step]);

  const [doing, setDoing] = useState(false);
  const createAgent = useCallback(async () => {
    const t = await firstTemplate();
    if (!t) throw new Error("No templates are available.");
    const agent = await createAgentFromTemplate(qc, t, idempotencyKey());
    toast({ tone: "success", title: "Agent created from template", description: `${agent.name} is saved as version 1.` });
    navigate(agentEditPath(agent.id));
  }, [qc, navigate]);

  const doIt = useCallback(async () => {
    const d = step.doIt;
    if (!d) return;
    if (d.click) {
      const el = document.querySelector<HTMLElement>(d.click);
      if (!el) return;
      // Radix tabs switch on pointer down, links and buttons on click: send both.
      const opts = { bubbles: true, cancelable: true, button: 0 };
      const Pointer = typeof PointerEvent === "function" ? PointerEvent : MouseEvent;
      el.dispatchEvent(new Pointer("pointerdown", opts));
      el.dispatchEvent(new MouseEvent("mousedown", opts));
      el.dispatchEvent(new Pointer("pointerup", opts));
      el.dispatchEvent(new MouseEvent("mouseup", opts));
      el.click();
      return;
    }
    if (d.action === "create-agent") {
      setDoing(true);
      try {
        await createAgent();
      } catch (e) {
        toast({ tone: "error", title: "Agent not created", description: problemMessage(e, "template") });
      } finally {
        setDoing(false);
      }
    }
  }, [step, createAgent]);

  const api_: TourApi = useMemo(
    () => ({
      state,
      start: () => {
        setAgentId(null);
        writeAgent(null);
        dispatch({ type: "start" });
      },
      resume: () => dispatch({ type: "resume" }),
      skip: () => dispatch({ type: "skip" }),
    }),
    [state],
  );

  const progress: StepProgress = {
    waiting: Boolean(step.doneWhen) && !baselineDone && !doneNow,
    done: baselineDone || doneNow,
  };

  return (
    <TourContext.Provider value={api_}>
      {children}
      {state.phase === "offer" && <WelcomeCard onStart={api_.start} onDecline={() => dispatch({ type: "decline" })} />}
      {running && (
        <TourOverlay
          key="tour"
          step={step}
          index={state.index}
          agentId={agentId}
          progress={progress}
          doing={doing}
          onNext={() => dispatch({ type: "next" })}
          onBack={() => dispatch({ type: "back" })}
          onSkip={() => dispatch({ type: "skip" })}
          onPause={() => dispatch({ type: "pause" })}
          onFinish={() => dispatch({ type: "finish" })}
          onDoIt={() => void doIt()}
        />
      )}
      {state.phase === "paused" && <ResumeChip index={state.index} onResume={api_.resume} onEnd={api_.skip} />}
      <p className="sr-only" aria-live="polite">
        {announcement}
      </p>
    </TourContext.Provider>
  );
}
