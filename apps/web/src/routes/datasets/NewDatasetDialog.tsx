/**
 * "New dataset" form (US5, T082, T095, FR-036): a name and an agent are required. Pressing Create
 * with either missing shows a message under each missing field and sends nothing; server errors
 * show next to the field they concern (a name already in use, any case, appears under Name).
 * Optional initial calls come from the "Add to dataset" menu.
 */
import { Database } from "lucide-react";
import { useState } from "react";
import { createDataset, type Dataset } from "../../api/datasets";
import { isApiError } from "../../api/errors";
import { fieldErrors } from "../../api/problems";
import { Button, Dialog, Field, Input, ProblemAlert, Select, Textarea, toast } from "../../components";
import { useAllAgents } from "../../api/agents";
import { describeAddResult } from "../simulations/invalidCalls";
import { bodyLimits } from "../../lib/contract.gen";

type Errors = { name?: string; agent?: string; description?: string };

export function NewDatasetDialog({
  open,
  onOpenChange,
  defaultAgentId,
  lockAgent = false,
  callIds,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  defaultAgentId?: string | null;
  /** The agent is fixed (creating from calls of one agent). */
  lockAgent?: boolean;
  callIds?: string[];
  onCreated: (d: Dataset) => void;
}) {
  const agents = useAllAgents();
  const [name, setName] = useState("");
  const [agentId, setAgentId] = useState(defaultAgentId ?? "");
  const [description, setDescription] = useState("");
  const [errors, setErrors] = useState<Errors>({});
  const [error, setError] = useState<unknown>(null);
  const [pending, setPending] = useState(false);
  const options = (agents.data ?? []).map((a) => ({ value: a.id, label: a.name }));
  if (agentId && !options.some((o) => o.value === agentId)) options.unshift({ value: agentId, label: "This call's agent" });

  const submit = async () => {
    const next: Errors = {};
    if (!name.trim()) next.name = "Enter a name";
    if (!agentId) next.agent = "Choose an agent";
    setErrors(next);
    setError(null);
    if (Object.keys(next).length) return;
    setPending(true);
    try {
      const d = await createDataset({
        name: name.trim(),
        agent_id: agentId,
        description: description.trim() || null,
        ...(callIds?.length && { call_ids: callIds }),
      });
      toast({ tone: "success", title: `Created ${d.name}`, ...(d.add_result && { description: describeAddResult(d.add_result) }) });
      onCreated(d);
      onOpenChange(false);
    } catch (e) {
      if (isApiError(e) && e.status === 409) {
        setErrors({ name: fieldErrors(e).name ?? e.problem.detail ?? "That name is already in use. Choose another name." });
      } else {
        const fe = fieldErrors(e);
        const mapped: Errors = { name: fe.name, agent: fe.agent_id, description: fe.description };
        if (mapped.name || mapped.agent || mapped.description) setErrors(mapped);
        else setError(e);
      }
    } finally {
      setPending(false);
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      icon={<Database aria-hidden />}
      title="New dataset"
      description="A named set of completed calls of one agent, kept as a regression suite."
      footer={
        <>
          <Button onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button variant="primary" pending={pending} onClick={() => void submit()}>
            {callIds?.length ? "Create and add" : "Create"}
          </Button>
        </>
      }
    >
      <form
        noValidate
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <Field label="Name" error={errors.name}>
          {({ id, describedBy, invalid }) => (
            <Input
              id={id}
              aria-describedby={describedBy}
              aria-invalid={invalid}
              maxLength={bodyLimits["POST /datasets"].name.maxLength}
              value={name}
              placeholder="Billing disputes, hard cases"
              onChange={(e) => {
                setName(e.target.value);
                if (errors.name) setErrors((x) => ({ ...x, name: undefined }));
              }}
            />
          )}
        </Field>
        <Field label="Agent" error={errors.agent} hint={lockAgent ? "Datasets hold calls of one agent." : undefined}>
          {({ id, describedBy, invalid }) => (
            <Select
              id={id}
              describedBy={describedBy}
              invalid={invalid}
              disabled={lockAgent}
              placeholder="Choose an agent"
              value={agentId || undefined}
              onValueChange={(v) => {
                setAgentId(v);
                if (errors.agent) setErrors((x) => ({ ...x, agent: undefined }));
              }}
              options={options}
            />
          )}
        </Field>
        <Field label="Description" hint="Optional." error={errors.description}>
          {({ id, describedBy, invalid }) => (
            <Textarea
              id={id}
              aria-describedby={describedBy}
              aria-invalid={invalid}
              rows={2}
              maxLength={bodyLimits["POST /datasets"].description.maxLength}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          )}
        </Field>
        <button type="submit" hidden aria-hidden tabIndex={-1} />
        <ProblemAlert error={error} kind="dataset" />
      </form>
    </Dialog>
  );
}
