import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useId, useState, type FormEvent } from "react";
import { api, unwrap } from "../../api/client";
import { fieldErrors, problemMessage } from "../../api/problems";
import { qk, useMe } from "../../api/queries";
import type { Me, Workspace } from "../../api/types";
import { GearSix } from "@phosphor-icons/react";
import { Building2, CircleAlert, Disc, Gauge, Mail, PenLine, RotateCcw, Save, ShieldCheck } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import {
  Button,
  EmptyState,
  FieldRow,
  InfoRow,
  Input,
  LeaveGuard,
  PageHeader,
  Panel,
  PanelRows,
  Skeleton,
  SwitchControl,
  WorkLayout,
  toast,
} from "../../components";

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
      <PageHeader title="Settings" description="Workspace name and the defaults new calls start with." />
      {me.isPending ? (
        <div className="flex max-w-[760px] flex-col gap-4">
          <Skeleton className="h-44 w-full rounded-panel" />
          <Skeleton className="h-28 w-full rounded-panel" />
        </div>
      ) : me.isError ? (
        <EmptyState icon={<GearSix weight="duotone" />} title="Settings did not load">
          {problemMessage(me.error, "workspace")}
        </EmptyState>
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

  const nameId = useId();
  const nameErr = serverErr.name ?? localErr;
  return (
    <WorkLayout
      main={
        <form onSubmit={onSubmit} noValidate>
          <LeaveGuard when={dirty && !save.isPending} />
          <Panel
            title="Workspace"
            description="Your workspace name and the defaults new calls start with."
            icon={<Building2 />}
            className={dirty ? "live-border" : undefined}
            bodyClassName="p-0"
          >
            <PanelRows>
              <FieldRow icon={<PenLine />} label="Workspace name" htmlFor={nameId} description="Shown in the top bar and the account menu.">
                <Input
                  id={nameId}
                  className="w-full"
                  value={name}
                  maxLength={NAME_MAX + 20}
                  onChange={(e) => setName(e.target.value)}
                  aria-describedby={`${nameId}-msg`}
                  aria-invalid={Boolean(nameErr)}
                />
                <div id={`${nameId}-msg`} className="flex w-full items-start justify-between gap-3 text-[13px]">
                  {nameErr ? (
                    <p role="alert" className="flex items-start gap-1.5 text-danger-text">
                      <CircleAlert className="mt-px size-3.5 shrink-0" aria-hidden />
                      {nameErr}
                    </p>
                  ) : (
                    <span />
                  )}
                  <span className="shrink-0 font-mono text-fg-3 tnum">
                    {name.length}/{NAME_MAX}
                  </span>
                </div>
              </FieldRow>
              <FieldRow
                inline
                icon={<Disc />}
                label="Record calls by default"
                htmlFor={`${nameId}-rec`}
                descriptionId={`${nameId}-rec-d`}
                description="Agents set to follow the workspace record their calls."
                hint="Each agent can override this default. A change applies to calls that start after you save."
              >
                <SwitchControl id={`${nameId}-rec`} checked={recording} onCheckedChange={setRecording} describedBy={`${nameId}-rec-d`} />
              </FieldRow>
            </PanelRows>
            <div className="flex flex-wrap items-center gap-3 border-t border-line bg-surface-2/50 px-5 py-3.5">
              <Button type="submit" variant="primary" pending={save.isPending} disabled={!dirty} icon={<Save aria-hidden />}>
                Save changes
              </Button>
              <Button
                variant="ghost"
                icon={<RotateCcw aria-hidden />}
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
              <AnimatePresence>
                {dirty && (
                  <motion.span
                    initial={{ opacity: 0, x: -4 }}
                    animate={{ opacity: 1, x: 0 }}
                    exit={{ opacity: 0 }}
                    className="ml-auto text-[13px] text-warning-text"
                  >
                    Unsaved changes
                  </motion.span>
                )}
              </AnimatePresence>
            </div>
          </Panel>

          {save.error && !serverErr.name && (
            <p role="alert" className="mt-4 text-[13px] text-danger-text">
              {problemMessage(save.error, "workspace")}
            </p>
          )}
        </form>
      }
      inspector={
        <Panel title="Limits and account" description="Contact support to change these." icon={<ShieldCheck />} bodyClassName="p-0">
          <PanelRows as="dl">
            <InfoRow
              icon={<Gauge />}
              label="Concurrent calls"
              hint="The most calls this workspace can have in progress at the same moment. A new call past the limit is refused, and its record says why."
            >
              <span className="font-mono tnum">{me.workspace.concurrency_limit}</span> at once
            </InfoRow>
            <InfoRow icon={<Mail />} label="Account email" title={me.user.email}>
              {me.user.email}
            </InfoRow>
          </PanelRows>
        </Panel>
      }
    />
  );
}
