import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CircleAlert, Radio, Rocket } from "lucide-react";
import { useState } from "react";
import { agentKeys, type ConfigIssue, type VersionRef } from "../../../api/agents";
import { api } from "../../../api/client";
import { ApiError, toProblem } from "../../../api/errors";
import { problemMessage } from "../../../api/problems";
import { Badge, Button, Dialog, Tooltip, toast } from "../../../components";
import { labelFor } from "./versionLabels";

/** Publish and unpublish with the blocker dialog, shared by the editor header and the history drawer. */
export function usePublish(agentId: string) {
  const qc = useQueryClient();
  const [blockers, setBlockers] = useState<ConfigIssue[] | null>(null);
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: agentKeys.detail(agentId) });
    void qc.invalidateQueries({ queryKey: agentKeys.versions(agentId) });
    void qc.invalidateQueries({ queryKey: ["agents", "list"] });
  };
  const publish = useMutation({
    mutationFn: async (v: { id: string; number: number }) => {
      const { response, error } = await api.PUT("/agents/{agent_id}/published-version", {
        params: { path: { agent_id: agentId } },
        body: { version_id: v.id },
      });
      if (!response.ok) throw new ApiError(response.status, toProblem(response.status, error));
      return v;
    },
    onSuccess: (v) => {
      refresh();
      toast({
        tone: "success",
        title: `Version ${v.number} published`,
        description: "New calls use it within a few seconds. Calls in progress keep their version.",
      });
    },
    onError: (e) => {
      if (e instanceof ApiError && e.status === 422 && e.problem.errors?.length)
        setBlockers(e.problem.errors.map((x) => ({ pointer: x.pointer, code: x.code, message: x.message })));
      else toast({ tone: "error", title: "Not published", description: problemMessage(e, "version") });
    },
  });
  const unpublish = useMutation({
    mutationFn: async () => {
      const { response, error } = await api.DELETE("/agents/{agent_id}/published-version", { params: { path: { agent_id: agentId } } });
      if (!response.ok) throw new ApiError(response.status, toProblem(response.status, error));
    },
    onSuccess: () => {
      refresh();
      toast({ tone: "success", title: "Agent unpublished", description: "Live channels refuse new calls until you publish a version." });
    },
    onError: (e) => toast({ tone: "error", title: "Not unpublished", description: problemMessage(e) }),
  });
  const blockerDialog = (
    <Dialog
      open={blockers !== null}
      onOpenChange={(o) => !o && setBlockers(null)}
      icon={<CircleAlert />}
      title="This version cannot go live yet"
      description="Replace these components, save, then publish the new version."
      footer={<Button onClick={() => setBlockers(null)}>Close</Button>}
    >
      <ul className="flex flex-col gap-2">
        {(blockers ?? []).map((b) => (
          <li key={`${b.pointer}${b.code}`} className="flex items-start gap-2">
            <CircleAlert className="mt-0.5 size-3.5 shrink-0 text-warning-text" aria-hidden />
            <span>
              <span className="font-medium text-fg">{labelFor(b.pointer)}</span>: {b.message}
            </span>
          </li>
        ))}
      </ul>
    </Dialog>
  );
  return { publish, unpublish, blockerDialog };
}

/**
 * Header control (T062): "Publish version N" for the saved draft, or a live badge when the draft
 * version is already published. Unsaved edits must be saved first, so a published version always
 * matches something the operator saved.
 */
export function PublishButton({
  agentId,
  draftVersion,
  published,
  dirty,
  blocked,
}: {
  agentId: string;
  draftVersion: VersionRef;
  published: VersionRef | null;
  dirty: boolean;
  blocked: boolean;
}) {
  const { publish, blockerDialog } = usePublish(agentId);
  if (published && published.id === draftVersion.id && !dirty) {
    return (
      <Badge tone="success" icon={<Radio />} className="h-9 rounded-control px-3 text-[13px]">
        Live on version {published.version_number}
      </Badge>
    );
  }
  const reason = dirty
    ? "Save your changes first, then publish the new version."
    : blocked
      ? "Fix the publish blockers listed under Checks first."
      : null;
  const button = (
    <Button
      icon={<Rocket aria-hidden />}
      pending={publish.isPending}
      disabled={Boolean(reason)}
      onClick={() => publish.mutate({ id: draftVersion.id, number: draftVersion.version_number })}
    >
      Publish version {draftVersion.version_number}
    </Button>
  );
  return (
    <>
      {reason ? (
        <Tooltip content={reason}>
          <span tabIndex={0} className="rounded-control focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring">
            {button}
          </span>
        </Tooltip>
      ) : (
        button
      )}
      {blockerDialog}
    </>
  );
}
