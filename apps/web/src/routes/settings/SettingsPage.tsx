import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { api, unwrap } from "../../api/client";
import { fieldErrors, problemMessage } from "../../api/problems";
import { qk, useMe } from "../../api/queries";
import type { Me, Workspace } from "../../api/types";
import { Button, EmptyState, Field, Input, Label, LeaveGuard, PageHeader, Panel, Skeleton, Switch, toast } from "../../components";

const NAME_MAX = 80;

export function nameError(name: string): string | null {
  if (name.trim().length === 0) return "Enter a workspace name.";
  if (name.trim().length > NAME_MAX) return `Keep the name to ${NAME_MAX} characters or fewer.`;
  return null;
}

/**
 * Settings (T093, FR-017): workspace name and call recording default are edited and saved
 * together with one Save; concurrency limit and account email are read-only. Unsaved edits are
 * guarded against navigation, reload and tab close.
 */
export function SettingsPage() {
  const me = useMe();
  return (
    <>
      <PageHeader title="Settings" description="Workspace details and defaults for new calls." />
      {me.isPending ? (
        <div className="flex max-w-[720px] flex-col gap-4">
          <Skeleton className="h-40 w-full" />
          <Skeleton className="h-28 w-full" />
        </div>
      ) : me.isError ? (
        <EmptyState title="Settings did not load">{problemMessage(me.error, "workspace")}</EmptyState>
      ) : (
        <SettingsForm key={me.data.workspace.id} me={me.data} />
      )}
    </>
  );
}

function SettingsForm({ me }: { me: Me }) {
  const qc = useQueryClient();
  const [saved, setSaved] = useState({ name: me.workspace.name, recording: me.workspace.recording_default });
  const [name, setName] = useState(saved.name);
  const [recording, setRecording] = useState(saved.recording);
  const [submitted, setSubmitted] = useState(false);

  const dirty = name !== saved.name || recording !== saved.recording;
  const localErr = submitted ? nameError(name) : null;

  const save = useMutation({
    mutationFn: (body: { name?: string; recording_default?: boolean }) => unwrap(api.PATCH("/workspaces/current", { body })),
    onSuccess: (ws: Workspace) => {
      setSaved({ name: ws.name, recording: ws.recording_default });
      setName(ws.name);
      setRecording(ws.recording_default);
      setSubmitted(false);
      qc.setQueryData<Me>(qk.me, (old) => (old ? { ...old, workspace: ws } : old));
      toast({ tone: "success", title: "Settings saved" });
    },
  });
  const serverErr = fieldErrors(save.error);

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    setSubmitted(true);
    if (nameError(name) || !dirty) return;
    const body: { name?: string; recording_default?: boolean } = {};
    if (name !== saved.name) body.name = name.trim();
    if (recording !== saved.recording) body.recording_default = recording;
    save.mutate(body);
  };

  return (
    <form onSubmit={onSubmit} noValidate className="flex max-w-[720px] flex-col gap-5">
      <LeaveGuard when={dirty && !save.isPending} />
      <Panel title="Workspace">
        <div className="flex flex-col gap-5">
          <Field label="Workspace name" error={serverErr.name ?? localErr} aside={<span className="font-mono text-[11px] text-fg-3 tnum">{name.length}/{NAME_MAX}</span>}>
            {({ id, describedBy, invalid }) => (
              <Input id={id} value={name} maxLength={NAME_MAX + 20} onChange={(e) => setName(e.target.value)} aria-describedby={describedBy} aria-invalid={invalid} />
            )}
          </Field>
          <Switch
            checked={recording}
            onCheckedChange={setRecording}
            label="Record calls by default"
            description="Agents set to follow the workspace record their calls. Each agent can override this."
          />
        </div>
      </Panel>

      <Panel title="Limits and account" description="Contact support to change these.">
        <dl className="grid gap-5 sm:grid-cols-2">
          <div className="flex flex-col gap-1.5">
            <dt>
              <Label>Concurrent calls</Label>
            </dt>
            <dd className="font-mono text-[14px] text-fg tnum">{me.workspace.concurrency_limit} at once</dd>
          </div>
          <div className="flex flex-col gap-1.5">
            <dt>
              <Label>Account email</Label>
            </dt>
            <dd className="truncate text-[14px] text-fg">{me.user.email}</dd>
          </div>
        </dl>
      </Panel>

      {save.error && !serverErr.name && (
        <p role="alert" className="text-[13px] text-danger-text">
          {problemMessage(save.error, "workspace")}
        </p>
      )}

      <div className="flex items-center gap-3">
        <Button type="submit" variant="primary" pending={save.isPending} disabled={!dirty}>
          Save changes
        </Button>
        <Button
          variant="ghost"
          disabled={!dirty || save.isPending}
          onClick={() => {
            setName(saved.name);
            setRecording(saved.recording);
            setSubmitted(false);
            save.reset();
          }}
        >
          Discard
        </Button>
        {dirty && <span className="text-[12.5px] text-amber-text">Unsaved changes</span>}
      </div>
    </form>
  );
}
