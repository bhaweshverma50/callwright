import { useMutation, useQueryClient } from "@tanstack/react-query";
import { BookOpen, BrainCircuit, ChevronLeft, CircleAlert, GitCompareArrows, History, Mic2, Radio, RotateCcw, Rocket, Wrench } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useState, type ReactNode } from "react";
import {
  type AgentDetail,
  agentChanged,
  restoreVersion,
  type SaveResult,
  useAgentVersions,
  useLlmCatalog,
  useProviderVoices,
  type VersionSource,
  type VersionSummary,
} from "../../../api/agents";
import { problemMessage } from "../../../api/problems";
import {
  Badge,
  Button,
  Dialog,
  Drawer,
  EmptyState,
  Menu,
  MenuContent,
  MenuItem,
  MenuTrigger,
  Skeleton,
  Tooltip,
  TruncatedText,
  cn,
  toast,
} from "../../../components";
import { llmLabel } from "../editor/catalogs";
import { usePublish } from "./PublishButton";
import { VersionCompare } from "./VersionCompare";
import { timeAgo } from "../../../lib/format";
import { isApiError } from "../../../api/errors";

const SOURCE: Record<VersionSource, string> = {
  create: "Created",
  save: "Saved",
  restore: "Restored",
  template: "Created from a template",
  duplicate: "Copied from another agent",
  flow_publish: "Published from the flow builder",
  test: "Snapshot for a test call",
};

function VoiceName({ provider, id }: { provider: string; id: string }) {
  const voices = useProviderVoices(provider, {});
  return <>{voices.data?.items.find((v) => v.voice_id === id)?.name ?? id}</>;
}

/**
 * Version history (T061, T062, T100, US3): newest first with live and draft badges, how each
 * version was made, its note and author, and what it runs (model, voice, tools, knowledge).
 * Compare opens in the drawer; restore asks once whether to also publish (3 clicks, SC-008).
 */
export function VersionDrawer({
  open,
  onOpenChange,
  agent,
  revision,
  dirty,
  onRestored,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  agent: AgentDetail;
  revision: number;
  dirty: boolean;
  onRestored: (r: SaveResult) => void;
}) {
  const qc = useQueryClient();
  const versions = useAgentVersions(agent.id, open);
  const llm = useLlmCatalog();
  const { publish, unpublish, blockerDialog } = usePublish(agent.id);
  const [compare, setCompare] = useState<{ version: VersionSummary; against: string } | null>(null);
  const [restoring, setRestoring] = useState<VersionSummary | null>(null);
  const [confirmUnpublish, setConfirmUnpublish] = useState(false);
  const items = versions.data?.items ?? [];
  const single = items.length === 1;
  const live = items.find((v) => v.is_published);

  const restore = useMutation({
    mutationFn: async ({ v, andPublish }: { v: VersionSummary; andPublish: boolean }) => ({
      result: await restoreVersion(agent.id, v.id, revision, andPublish),
      v,
      andPublish,
    }),
    onSuccess: ({ result, v, andPublish }) => {
      setRestoring(null);
      onRestored(result);
      agentChanged(qc, result.agent);
      toast({
        tone: "success",
        title: `Version ${v.version_number} restored as version ${result.version.version_number}`,
        description: andPublish
          ? "It is live now."
          : live
            ? `Live calls still use version ${live.version_number}.`
            : "Publish it when you are ready.",
      });
    },
    onError: (e) => {
      setRestoring(null);
      toast({
        tone: "error",
        title: "Not restored",
        description: isApiError(e) && e.status === 412 ? "This agent changed in another tab. Reload it, then restore." : problemMessage(e, "version"),
      });
    },
  });

  return (
    <Drawer
      open={open}
      onOpenChange={(o) => {
        onOpenChange(o);
        if (!o) setCompare(null);
      }}
      width="lg"
      title={compare ? `Version ${compare.version.version_number}` : "Version history"}
      meta={compare ? "What changed, field by field." : "Every save records a version. Live calls use the published one."}
      actions={
        compare ? (
          <Button variant="ghost" size="sm" icon={<ChevronLeft aria-hidden />} onClick={() => setCompare(null)}>
            All versions
          </Button>
        ) : undefined
      }
    >
      <AnimatePresence mode="wait" initial={false}>
        {compare ? (
          <motion.div
            key="compare"
            initial={{ opacity: 0, x: 12 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 12 }}
            transition={{ duration: 0.2 }}
          >
            <VersionCompare
              agentId={agent.id}
              version={compare.version}
              against={compare.against}
              versions={items}
              onAgainstChange={(against) => setCompare({ ...compare, against })}
            />
          </motion.div>
        ) : (
          <motion.div
            key="list"
            initial={{ opacity: 0, x: -12 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -12 }}
            transition={{ duration: 0.2 }}
            className="flex flex-col gap-3"
          >
            {live ? (
              <div className="flex items-center justify-between gap-3 rounded-panel bg-success-soft/60 px-4 py-3">
                <span className="flex items-center gap-2 text-[13px] text-fg">
                  <Radio className="size-4 text-success-text" aria-hidden /> Live calls use version {live.version_number}.
                </span>
                <Button size="sm" variant="ghost" onClick={() => setConfirmUnpublish(true)}>
                  Unpublish
                </Button>
              </div>
            ) : (
              items.length > 0 && (
                <div className="flex items-center gap-2 rounded-panel bg-warning-soft/60 px-4 py-3 text-[13px] text-fg">
                  <CircleAlert className="size-4 text-warning-text" aria-hidden /> Not published: live channels refuse calls until you publish a
                  version.
                </div>
              )
            )}
            {versions.isPending ? (
              Array.from({ length: 3 }, (_, i) => <Skeleton key={i} className="h-36 w-full rounded-panel" />)
            ) : versions.isError ? (
              <EmptyState compact icon={<History />} title="History did not load">
                {problemMessage(versions.error, "agent")}
              </EmptyState>
            ) : (
              <ol className="flex flex-col gap-3" aria-label="Versions, newest first">
                {items.map((v, i) => {
                  const previous = items[i + 1];
                  return (
                    <motion.li
                      key={v.id}
                      layout
                      initial={{ opacity: 0, y: 6 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ duration: 0.22, delay: Math.min(i, 6) * 0.03 }}
                      className={cn("rounded-panel border bg-surface", v.is_draft ? "border-accent/50" : "border-line")}
                    >
                      <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-2 px-4 pt-3.5">
                        <div className="flex min-w-0 items-center gap-3">
                          <span
                            className={cn(
                              "grid size-9 shrink-0 place-items-center rounded-full font-mono text-[13px] font-medium tnum",
                              v.is_published ? "bg-accent text-white" : "bg-surface-2 text-fg-2",
                            )}
                          >
                            {v.version_number}
                          </span>
                          <div className="flex min-w-0 flex-col">
                            <span className="text-[14px] font-semibold text-fg">Version {v.version_number}</span>
                            <span className="text-[13px] text-fg-3">
                              {v.source === "restore" && v.restored_from_version_number
                                ? `Restored from version ${v.restored_from_version_number}`
                                : SOURCE[v.source]}
                              , {timeAgo(v.created_at)}
                            </span>
                          </div>
                        </div>
                        <div className="flex flex-wrap gap-1.5">
                          {v.is_published && (
                            <Badge tone="success" icon={<Radio />}>
                              Live
                            </Badge>
                          )}
                          {v.is_draft && <Badge tone="accent">In the editor</Badge>}
                          {v.has_publish_blockers && (
                            <Badge tone="warning" icon={<CircleAlert />}>
                              Cannot go live
                            </Badge>
                          )}
                        </div>
                      </div>
                      {v.note && <p className="mx-4 mt-2.5 rounded-control bg-surface-2/60 px-3 py-2 text-[13px] text-fg-2">{v.note}</p>}
                      {v.summary && (
                        <dl className="mx-4 mt-3 grid grid-cols-2 gap-x-4 gap-y-1.5 text-[13px] sm:grid-cols-4">
                          <SummaryItem icon={<BrainCircuit />} label="Model">
                            {llmLabel(llm.data, v.summary.llm_model)}
                          </SummaryItem>
                          <SummaryItem icon={<Mic2 />} label="Voice">
                            <VoiceName provider={v.summary.tts_provider} id={v.summary.tts_voice_id} />
                          </SummaryItem>
                          <SummaryItem icon={<Wrench />} label="Tools">
                            {v.summary.tool_count}
                          </SummaryItem>
                          <SummaryItem icon={<BookOpen />} label="Knowledge">
                            {v.summary.kb_count}
                          </SummaryItem>
                        </dl>
                      )}
                      <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-line px-4 py-2.5">
                        {v.created_by_email && (
                          <TruncatedText className="mr-auto min-w-0 max-w-[50%] text-[12px] text-fg-3">{v.created_by_email}</TruncatedText>
                        )}
                        {!v.created_by_email && <span className="mr-auto" />}
                        {single ? (
                          <Tooltip content="Nothing to compare yet: this agent has one version.">
                            <span tabIndex={0} className="rounded-control focus-visible:outline-2 focus-visible:outline-ring">
                              <Button size="sm" variant="ghost" icon={<GitCompareArrows aria-hidden />} disabled>
                                Compare
                              </Button>
                            </span>
                          </Tooltip>
                        ) : (
                          <Menu>
                            <MenuTrigger asChild>
                              <Button size="sm" variant="ghost" icon={<GitCompareArrows aria-hidden />}>
                                Compare
                              </Button>
                            </MenuTrigger>
                            <MenuContent>
                              <MenuItem onSelect={() => setCompare({ version: v, against: "draft" })}>With the current draft</MenuItem>
                              {previous && (
                                <MenuItem onSelect={() => setCompare({ version: v, against: previous.id })}>
                                  With version {previous.version_number}
                                </MenuItem>
                              )}
                              {live && live.id !== v.id && (
                                <MenuItem onSelect={() => setCompare({ version: v, against: live.id })}>
                                  With the live version ({live.version_number})
                                </MenuItem>
                              )}
                            </MenuContent>
                          </Menu>
                        )}
                        {!v.is_draft && !single && (
                          <Button size="sm" variant="ghost" icon={<RotateCcw aria-hidden />} onClick={() => setRestoring(v)}>
                            Restore
                          </Button>
                        )}
                        {!v.is_published && (
                          <Button
                            size="sm"
                            variant="secondary"
                            icon={<Rocket aria-hidden />}
                            pending={publish.isPending && publish.variables?.id === v.id}
                            onClick={() => publish.mutate({ id: v.id, number: v.version_number })}
                          >
                            Publish
                          </Button>
                        )}
                      </div>
                    </motion.li>
                  );
                })}
              </ol>
            )}
          </motion.div>
        )}
      </AnimatePresence>

      <Dialog
        open={restoring !== null}
        onOpenChange={(o) => !o && setRestoring(null)}
        icon={<RotateCcw />}
        title={`Restore version ${restoring?.version_number ?? ""}?`}
        description={`Its configuration becomes the draft and is saved as a new version. ${live ? `Live calls keep version ${live.version_number} unless you also publish.` : "Nothing is live until you publish."}`}
        footer={
          <>
            <Button
              pending={restore.isPending && !restore.variables?.andPublish}
              disabled={restore.isPending}
              onClick={() => restoring && restore.mutate({ v: restoring, andPublish: false })}
            >
              Restore to draft
            </Button>
            <Button
              variant="primary"
              pending={restore.isPending && restore.variables?.andPublish}
              disabled={restore.isPending}
              onClick={() => restoring && restore.mutate({ v: restoring, andPublish: true })}
            >
              Restore and publish
            </Button>
          </>
        }
      >
        {dirty && (
          <p className="flex items-start gap-2 rounded-control bg-warning-soft/70 px-3 py-2 text-[13px] text-fg">
            <CircleAlert className="mt-0.5 size-4 shrink-0 text-warning-text" aria-hidden /> Your unsaved changes in the editor will be replaced.
          </p>
        )}
      </Dialog>
      <Dialog
        open={confirmUnpublish}
        onOpenChange={setConfirmUnpublish}
        role="alertdialog"
        icon={<CircleAlert />}
        size="sm"
        title="Unpublish this agent?"
        description="Phone numbers and other live channels refuse new calls until you publish a version again. Calls in progress finish normally."
        footer={
          <>
            <Button autoFocus onClick={() => setConfirmUnpublish(false)}>
              Keep it live
            </Button>
            <Button
              variant="danger"
              pending={unpublish.isPending}
              onClick={() => unpublish.mutate(undefined, { onSettled: () => setConfirmUnpublish(false) })}
            >
              Unpublish
            </Button>
          </>
        }
      />
      {blockerDialog}
    </Drawer>
  );
}

function SummaryItem({ icon, label, children }: { icon: ReactNode; label: string; children: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5">
      <dt className="flex items-center gap-1 text-[12px] text-fg-3 [&_svg]:size-3">
        {icon}
        {label}
      </dt>
      <dd className="min-w-0 text-fg">
        <TruncatedText>{children}</TruncatedText>
      </dd>
    </div>
  );
}
