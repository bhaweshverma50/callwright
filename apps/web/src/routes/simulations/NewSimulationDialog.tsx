/**
 * "New simulation" (US4, T094, FR-035): a standalone persona run without Call History. Choose the
 * agent and target, write a persona brief, check the pre-flight, start. Works for agents with no
 * calls yet.
 */
import { UserRoundPlus } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router";
import { useAgentOptions } from "../../api/calls";
import { isRetryable, useActionKey } from "../../api/paid";
import { preflight, startSimulationRun, type PersonaBrief, type Preflight } from "../../api/simulations";
import { Button, Dialog, Field, Input, Select, toast } from "../../components";
import { PersonaBriefEditor, cleanBrief, emptyBrief } from "./PersonaBriefEditor";
import { PreflightStep } from "./PreflightDialog";
import { ProblemAlert } from "./shared";
import { TargetPicker, VariantEditor, defaultTarget, toSimTarget, useTargetSources, type TargetChoice } from "./VariantEditor";

function Target({ agentId, value, onChange }: { agentId: string; value: TargetChoice; onChange: (t: TargetChoice) => void }) {
  const sources = useTargetSources(agentId);
  return (
    <>
      <Field label="Run against">{({ id }) => <TargetPicker id={id} agentId={agentId} value={value} onChange={onChange} />}</Field>
      {value.type === "variant" && value.variant && sources.agent.data && (
        <VariantEditor
          agent={sources.agent.data}
          graph={sources.graph}
          tools={sources.tools}
          value={value.variant}
          onChange={(v) => onChange({ ...value, variant: v })}
        />
      )}
    </>
  );
}

export function NewSimulationDialog({
  open,
  onOpenChange,
  defaultAgentId,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  defaultAgentId?: string | null;
}) {
  const navigate = useNavigate();
  const key = useActionKey();
  const agents = useAgentOptions();
  const [agentId, setAgentId] = useState(defaultAgentId ?? "");
  const [target, setTarget] = useState<TargetChoice>(defaultTarget);
  const [brief, setBrief] = useState<PersonaBrief>(emptyBrief);
  const [turnsText, setTurnsText] = useState("20");
  const [errors, setErrors] = useState<{ agent?: string; goal?: string }>({});
  const [report, setReport] = useState<Preflight | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [pending, setPending] = useState(false);
  const sources = useTargetSources(agentId);
  const turns = Math.min(50, Math.max(1, Number(turnsText) || 20));

  const changed = () => {
    key.reset();
    setError(null);
  };
  const simTarget = () => toSimTarget(target, sources.agent.data, sources.graph, sources.tools);

  const check = async () => {
    const next = { ...(!agentId && { agent: "Choose an agent" }), ...(!brief.goal.trim() && { goal: "Describe what the caller wants" }) };
    setErrors(next);
    if (Object.keys(next).length) return;
    setPending(true);
    setError(null);
    try {
      setReport(await preflight({ agent_id: agentId, mode: "persona", target: simTarget() }));
    } catch (e) {
      setError(e);
    } finally {
      setPending(false);
    }
  };

  const start = async () => {
    setPending(true);
    setError(null);
    try {
      const run = await startSimulationRun(
        {
          agent_id: agentId,
          mode: "persona",
          target: simTarget(),
          persona_brief: cleanBrief(brief),
          settings: { max_caller_turns: turns, missing_mock_policy: "synthesize" },
        },
        key.current(),
      );
      key.reset();
      toast({ tone: "success", title: "Simulation started", description: "The transcript opens when the run finishes." });
      onOpenChange(false);
      navigate(`/simulations/runs/${run.simulation_run_id}`);
    } catch (e) {
      if (!isRetryable(e)) key.reset();
      setError(e);
    } finally {
      setPending(false);
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      size="lg"
      icon={<UserRoundPlus aria-hidden />}
      title={report ? "Check before starting" : "New simulation"}
      description={
        report
          ? "Nothing is charged until you start."
          : "An LLM plays a caller from your brief and talks to the agent as text. No call history needed."
      }
      footer={
        report ? (
          <>
            <Button onClick={() => setReport(null)}>Back</Button>
            <Button variant="primary" pending={pending} onClick={() => void start()}>
              {report.tools_missing_mock.length ? "Run anyway" : "Start simulation"}
            </Button>
          </>
        ) : (
          <>
            <Button onClick={() => onOpenChange(false)}>Cancel</Button>
            <Button variant="primary" pending={pending} onClick={() => void check()}>
              Continue
            </Button>
          </>
        )
      }
    >
      {report ? (
        <div className="flex flex-col gap-4">
          <PreflightStep report={report} agentId={agentId} agentType={sources.agent.data?.type} />
          <ProblemAlert error={error} kind="simulation" />
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-[minmax(0,1fr)_140px]">
            <Field label="Agent" error={errors.agent}>
              {({ id, describedBy, invalid }) => (
                <Select
                  id={id}
                  describedBy={describedBy}
                  invalid={invalid}
                  placeholder="Choose an agent"
                  value={agentId || undefined}
                  onValueChange={(v) => {
                    setAgentId(v);
                    setTarget(defaultTarget());
                    setErrors((e) => ({ ...e, agent: undefined }));
                    changed();
                  }}
                  options={(agents.data ?? []).map((a) => ({ value: a.id, label: a.name }))}
                />
              )}
            </Field>
            <Field label="Turn limit" hint="1 to 50">
              {({ id, describedBy }) => (
                <Input
                  id={id}
                  aria-describedby={describedBy}
                  inputMode="numeric"
                  value={turnsText}
                  onChange={(e) => {
                    const d = e.target.value.replace(/\D/g, "");
                    setTurnsText(d === "" ? "" : String(Math.min(50, Math.max(1, Number(d)))));
                    changed();
                  }}
                  onBlur={() => turnsText === "" && setTurnsText("20")}
                />
              )}
            </Field>
          </div>
          {agentId && (
            <Target
              agentId={agentId}
              value={target}
              onChange={(t) => {
                setTarget(t);
                changed();
              }}
            />
          )}
          <PersonaBriefEditor
            value={brief}
            goalError={errors.goal}
            onChange={(b) => {
              setBrief(b);
              if (b.goal.trim()) setErrors((e) => ({ ...e, goal: undefined }));
              changed();
            }}
          />
          <ProblemAlert error={error} kind="simulation" />
        </div>
      )}
    </Dialog>
  );
}
