/**
 * Start a simulation from calls or a dataset (US2, US3, US5; T056, T059, T068). One base call
 * starts an individual run; two or more calls, or a dataset, start a batch. Choose replay or
 * persona and the target (published, saved draft, an earlier version, or a variant), then a
 * pre-flight step shows runs, cost and tools without mocks before anything is charged.
 * Mounted in Call History, the call detail drawer and the dataset page.
 */
import { FlaskConical } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router";
import { isRetryable, useActionKey } from "../../api/paid";
import {
  BATCH_MAX,
  BATCH_MIN,
  preflight,
  startExperiment,
  startSimulationRun,
  type Preflight,
  type SimMode,
  type SimSettings,
} from "../../api/simulations";
import { Button, Dialog, Field, FormAlert, Input, ProblemAlert, Segmented, toast } from "../../components";
import { PreflightStep } from "./PreflightDialog";
import { TargetPicker, VariantEditor, defaultTarget, toSimTarget, useTargetSources, variantChanges, type TargetChoice } from "./VariantEditor";
import { plural } from "../../lib/format";
import { bodyLimits } from "../../lib/contract.gen";
import { experimentPath, simulationRunPath } from "../../lib/paths";

export interface StartSimulationProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  agentId: string;
  agentName?: string;
  /** Base calls (one starts an individual run, two or more a batch). */
  baseCallIds?: string[];
  /** Or a whole dataset (always a batch). */
  dataset?: { id: string; name: string };
}

const MAX_TURNS = 50;

export function StartSimulationDialog({ open, onOpenChange, agentId, agentName, baseCallIds = [], dataset }: StartSimulationProps) {
  const navigate = useNavigate();
  const key = useActionKey();
  const sources = useTargetSources(agentId);
  const agent = sources.agent.data;
  const [mode, setMode] = useState<SimMode>("replay");
  const [target, setTarget] = useState<TargetChoice>(defaultTarget);
  const [name, setName] = useState("");
  const [turnsText, setTurnsText] = useState("20");
  const [report, setReport] = useState<Preflight | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [pending, setPending] = useState(false);

  const batch = Boolean(dataset) || baseCallIds.length > 1;
  const tooMany = !dataset && baseCallIds.length > BATCH_MAX;
  const turns = Math.min(MAX_TURNS, Math.max(1, Number(turnsText) || 20));
  const variantEmpty = target.type === "variant" && variantChanges(agent?.draft_config, target.variant) === 0;
  const changed = () => {
    key.reset();
    setReport(null);
    setError(null);
  };
  const simTarget = () => toSimTarget(target, agent, sources.graph, sources.tools);
  const settings = (): SimSettings => ({ missing_mock_policy: "synthesize", max_caller_turns: mode === "persona" ? turns : 20 });

  const check = async () => {
    setPending(true);
    setError(null);
    try {
      setReport(
        await preflight({
          agent_id: agentId,
          mode,
          target: simTarget(),
          ...(dataset ? { dataset_id: dataset.id } : { base_call_ids: baseCallIds }),
        }),
      );
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
      if (batch) {
        const exp = await startExperiment(
          {
            agent_id: agentId,
            mode,
            target: simTarget(),
            settings: settings(),
            ...(name.trim() && { name: name.trim() }),
            ...(dataset ? { dataset_id: dataset.id } : { base_call_ids: baseCallIds }),
          },
          key.current(),
        );
        key.reset();
        toast({ tone: "success", title: "Batch started", description: `${plural(exp.total_count, "run")} queued.` });
        onOpenChange(false);
        navigate(experimentPath(exp.experiment_id));
      } else {
        const run = await startSimulationRun(
          { agent_id: agentId, mode, base_call_id: baseCallIds[0]!, target: simTarget(), settings: settings() },
          key.current(),
        );
        key.reset();
        toast({ tone: "success", title: "Simulation started", description: "The comparison opens when the run finishes." });
        onOpenChange(false);
        navigate(simulationRunPath(run.simulation_run_id));
      }
    } catch (e) {
      if (!isRetryable(e)) key.reset();
      setError(e);
    } finally {
      setPending(false);
    }
  };

  const subject = dataset
    ? `the ${dataset.name} dataset`
    : baseCallIds.length === 1
      ? "this call"
      : `${plural(baseCallIds.length, "call")}${agentName ? ` of ${agentName}` : ""}`;
  const startLabel = report?.tools_missing_mock.length ? "Run anyway" : batch ? `Start ${plural(report?.run_count ?? 0, "run")}` : "Start simulation";

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      size="lg"
      icon={<FlaskConical aria-hidden />}
      title={report ? "Check before starting" : batch ? "Run a batch simulation" : "Run a simulation"}
      description={
        report
          ? "Nothing is charged until you start. Runs that never start are not charged."
          : `Re-run ${subject} as text against a version of the agent. Tools answer with their mock responses; nothing reaches real systems.`
      }
      footer={
        report ? (
          <>
            <Button onClick={() => setReport(null)}>Back</Button>
            <Button variant="primary" pending={pending} disabled={report.run_count === 0} onClick={() => void start()}>
              {startLabel}
            </Button>
          </>
        ) : (
          <>
            <Button onClick={() => onOpenChange(false)}>Cancel</Button>
            <Button
              variant="primary"
              pending={pending}
              disabled={tooMany || variantEmpty || (!dataset && baseCallIds.length === 0)}
              onClick={() => void check()}
            >
              Continue
            </Button>
          </>
        )
      }
    >
      {report ? (
        <div className="flex flex-col gap-4">
          <PreflightStep report={report} agentId={agentId} agentType={agent?.type} />
          <ProblemAlert error={error} kind="simulation" />
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          {tooMany && (
            <FormAlert tone="error">
              A batch takes {BATCH_MIN} to {BATCH_MAX} calls and {plural(baseCallIds.length, "call is", "calls are")} selected. Narrow the selection
              to {BATCH_MAX} or fewer.
            </FormAlert>
          )}
          <div className="flex flex-col gap-2">
            <span id="sim-mode-label" className="text-[13px] font-medium text-fg">
              Mode
            </span>
            <Segmented
              aria-labelledby="sim-mode-label"
              value={mode}
              onValueChange={(m) => {
                setMode(m);
                changed();
              }}
              options={[
                { value: "replay", label: "Replay" },
                { value: "persona", label: "Persona" },
              ]}
            />
            <p className="text-[13px] text-fg-3">
              {mode === "replay"
                ? "Feeds the recorded caller turns, in order, to the target. Cheapest; best for small prompt changes."
                : "An LLM plays the caller from a brief written from each call, and reacts to what the agent says. Use it after larger changes."}
            </p>
          </div>
          <Field label="Run against">
            {({ id }) => (
              <TargetPicker
                id={id}
                agentId={agentId}
                value={target}
                onChange={(t) => {
                  setTarget(t);
                  changed();
                }}
              />
            )}
          </Field>
          {sources.agent.isError && (
            <p className="text-[13px] text-fg-3">
              This agent's versions could not be loaded, so only the published version and saved draft are offered.
            </p>
          )}
          {target.type === "variant" && target.variant && agent && (
            <VariantEditor
              agent={agent}
              graph={sources.graph}
              tools={sources.tools}
              value={target.variant}
              onChange={(v) => {
                setTarget({ ...target, variant: v });
                changed();
              }}
            />
          )}
          {batch && (
            <Field label="Batch name" hint="Optional. Helps you find the batch later.">
              {({ id, describedBy }) => (
                <Input
                  id={id}
                  aria-describedby={describedBy}
                  maxLength={bodyLimits["POST /experiments"].name.maxLength}
                  value={name}
                  placeholder={dataset ? `${dataset.name}, replay` : "Shorter greeting check"}
                  onChange={(e) => {
                    setName(e.target.value);
                    changed();
                  }}
                />
              )}
            </Field>
          )}
          {mode === "persona" && (
            <Field
              label="Caller turn limit"
              hint="1 to 50. The run stops when the caller's goal is met, the agent hangs up, or this limit is reached."
            >
              {({ id, describedBy }) => (
                <Input
                  id={id}
                  aria-describedby={describedBy}
                  inputMode="numeric"
                  className="w-24"
                  value={turnsText}
                  onChange={(e) => {
                    const d = e.target.value.replace(/\D/g, "");
                    setTurnsText(d === "" ? "" : String(Math.min(MAX_TURNS, Math.max(1, Number(d)))));
                    changed();
                  }}
                  onBlur={() => turnsText === "" && setTurnsText("20")}
                />
              )}
            </Field>
          )}
          {variantEmpty && (
            <p className="text-[13px] text-fg-3">Edit the variant before continuing; an unchanged copy gives the same results as the draft.</p>
          )}
          <ProblemAlert error={error} kind="simulation" />
        </div>
      )}
    </Dialog>
  );
}
