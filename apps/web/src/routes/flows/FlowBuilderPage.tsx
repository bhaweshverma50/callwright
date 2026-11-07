import "./flows.css";
import { FlowArrow } from "@phosphor-icons/react";
import { useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, CircleAlert, History, ListChecks, MessageSquareText, Play, RefreshCw, Rocket, Save, Settings2 } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { agentKeys, useAgent, useLlmCatalog, useVoiceCatalog, type AgentDetail, type LlmCatalog, type VoiceCatalog } from "../../api/agents";
import { isApiError } from "../../api/errors";
import {
  fetchFlowByAgent,
  flowKeys,
  useFlowByAgent,
  type ConfigByNode,
  type Flow,
  type FlowEdge,
  type FlowNode,
  type StartConfig,
  type ValidationIssue,
} from "../../api/flows";
import { problemMessage } from "../../api/problems";
import { Badge, Button, CopyButton, Dialog, EmptyState, IconButton, Input, LeaveGuard, Skeleton, TabPanel, Tabs, cn, toast } from "../../components";
import { RecordNotFound } from "../NotFound";
import { AssistantPanel } from "./assistant/AssistantPanel";
import { ProposalBar, approveProposal, type Proposal } from "./assistant/ProposalBar";
import { diffGraphs } from "./canvas/diffOverlay";
import { EMPTY_SELECTION, FlowCanvas, type Selection } from "./canvas/FlowCanvas";
import { useFlow } from "./hooks/useFlow";
import { useFlowEvents } from "./hooks/useFlowEvents";
import { useValidate } from "./hooks/useValidate";
import { duplicateNodes, removeItems } from "./model";
import { EdgePanel } from "./panels/EdgePanel";
import { GlobalSettingsDrawer, SECTIONS, type SettingsSection } from "./panels/GlobalSettingsDrawer";
import { NodePanel } from "./panels/NodePanel";
import { PublishDialog } from "./panels/PublishDialog";
import { ValidationPanel } from "./panels/ValidationPanel";
import { FlowTestPanel } from "./test/FlowTestPanel";
import { isAgentId } from "../../lib/paths";
import { stable, useAgentDraft, VersionDrawer } from "../agents/config";

/**
 * Flow builder (T030, T108) at /agents/:id/flow: canvas, side panel and header. Loads the agent,
 * its flow and both catalogs, then hands a ready draft to the builder.
 */
export function FlowBuilderPage() {
  const { id = "" } = useParams();
  const valid = isAgentId(id);
  const agent = useAgent(valid ? id : undefined);
  const flow = useFlowByAgent(valid ? id : undefined);
  const llm = useLlmCatalog();
  const voice = useVoiceCatalog();
  const catalogs = useMemo(() => (llm.data && voice.data ? { llm: llm.data, voice: voice.data } : null), [llm.data, voice.data]);
  if (!valid) return <RecordNotFound kind="agent" backTo="/agents" backLabel="Back to Agents" />;
  const failed = agent.error ?? flow.error;
  if (failed) {
    if (isApiError(failed) && failed.status === 404) return <RecordNotFound kind="agent" backTo="/agents" backLabel="Back to Agents" />;
    return (
      <EmptyState icon={<FlowArrow weight="duotone" />} title="The flow did not load">
        {problemMessage(failed, "flow")}
      </EmptyState>
    );
  }
  if (!agent.data || !flow.data || !catalogs) return <BuilderSkeleton />;
  return <Builder key={flow.data.id} agent={agent.data} initial={flow.data} catalogs={catalogs} />;
}

type SideTab = "assistant" | "test" | "problems";

function Builder({ agent, initial, catalogs }: { agent: AgentDetail; initial: Flow; catalogs: { llm: LlmCatalog; voice: VoiceCatalog } }) {
  const qc = useQueryClient();
  const draft = useFlow(initial);
  const settings = useAgentDraft(
    { id: agent.id, name: agent.name, config: agent.draft_config, revision: agent.draft_revision, detail: agent },
    "flow",
  );
  const live = useAgent(agent.id);
  const detail = live.data ?? agent;
  const [params, setParams] = useSearchParams();
  const configure = params.get("configure") as SettingsSection | null;
  const [selection, setSelection] = useState<Selection>(EMPTY_SELECTION);
  const [tab, setTab] = useState<SideTab>(initial.last_validation.errors ? "problems" : "assistant");
  const [publishing, setPublishing] = useState(false);
  const [history, setHistory] = useState(() => params.get("history") === "1");
  const [conflict, setConflict] = useState<null | "flow_revision_conflict" | "agent_draft_changed">(null);
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [fitSignal, setFitSignal] = useState(0);
  const events = useFlowEvents();
  const validation = useValidate(draft.base.id, draft.graph, initial.last_validation);
  const issues = useMemo(() => validation.result?.issues ?? [], [validation.result]);
  const allowHttp = import.meta.env.DEV;

  const changedKeys = useMemo(() => {
    const out = new Set<string>();
    const before = settings.base.config as unknown as Record<string, unknown>;
    const now = settings.config as unknown as Record<string, unknown>;
    for (const k of Object.keys(now)) if (stable(now[k]) !== stable(before[k])) out.add(k);
    return out;
  }, [settings.base.config, settings.config]);
  const dirty = draft.dirty || changedKeys.size > 0;
  const nameError = draft.name.trim() ? null : "Give the agent a name.";

  const diff = useMemo(() => (proposal ? diffGraphs(draft.graph, proposal.graph) : null), [draft.graph, proposal]);
  const shownGraph = diff?.shown ?? draft.graph;

  const save = useCallback(async (): Promise<boolean> => {
    if (nameError) {
      toast({ tone: "error", title: "Not saved", description: nameError });
      return false;
    }
    const changes: Record<string, unknown> = {};
    for (const k of changedKeys) changes[k] = (settings.config as unknown as Record<string, unknown>)[k];
    const out = await draft.save(changedKeys.size ? { changes, draftRevision: settings.base.revision } : undefined);
    if (out.status === "saved") {
      validation.setResult(out.flow.last_validation);
      qc.setQueryData(flowKeys.byAgent(agent.id), out.flow);
      const fresh = await live.refetch();
      if (fresh.data) settings.resetTo(fresh.data);
      void qc.invalidateQueries({ queryKey: ["agents", "list"] });
      toast({
        tone: "success",
        title: "Saved",
        description: out.flow.last_validation.errors
          ? `${out.flow.last_validation.errors} problem${out.flow.last_validation.errors === 1 ? "" : "s"} to fix before publishing.`
          : undefined,
      });
      return true;
    }
    if (out.status === "conflict") setConflict(out.code);
    else if (out.status === "invalid") toast({ tone: "error", title: "Not saved", description: out.message });
    else toast({ tone: "error", title: "Not saved", description: problemMessage(out.error, "flow") });
    return false;
  }, [agent.id, changedKeys, draft, live, nameError, qc, settings, validation]);

  // Cmd or Ctrl + S saves.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "s") {
        e.preventDefault();
        if (!draft.saving && dirty) void save();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [dirty, draft.saving, save]);

  const locked = proposal !== null;
  const lockedNotice = useCallback(() => toast({ title: "Approve or decline the pending changes first" }), []);
  const selectedNode =
    selection.nodes.length === 1 && selection.edges.length === 0 ? draft.graph.nodes.find((n) => n.id === selection.nodes[0]) : undefined;
  const selectedEdge =
    selection.edges.length === 1 && selection.nodes.length === 0 ? draft.graph.edges.find((e) => e.id === selection.edges[0]) : undefined;
  const startNode = draft.graph.nodes.find((n) => n.type === "start") as FlowNode<"start"> | undefined;
  const variables = useMemo(() => variableNames(draft.graph.nodes), [draft.graph.nodes]);

  // Stable handlers for the canvas and the memoised side panels: a canvas drag or pan must not
  // hand them new props (that re-rendered every form on every frame of a drag).
  const { setGraph, undo } = draft;
  const graphRef = useRef(draft.graph);
  graphRef.current = draft.graph;
  const llmCatalog = catalogs.llm;
  const modelLabel = useCallback(
    (provider: string, model: string) => llmCatalog.providers.find((p) => p.id === provider)?.models.find((m) => m.id === model)?.label ?? model,
    [llmCatalog],
  );
  const closePanel = useCallback(() => setSelection(EMPTY_SELECTION), []);
  const selectEdge = useCallback((edgeId: string) => setSelection({ nodes: [], edges: [edgeId] }), []);
  const deleteNode = useCallback(
    (node: FlowNode) => {
      setGraph((g) => removeItems(g, new Set([node.id]), new Set()));
      setSelection(EMPTY_SELECTION);
      toast({ title: `Deleted ${node.label}`, action: { label: "Undo", onClick: undo } });
    },
    [setGraph, undo],
  );
  const duplicateNode = useCallback(
    (node: FlowNode) => {
      const { graph, created } = duplicateNodes(graphRef.current, [node.id]);
      setGraph(graph);
      setSelection({ nodes: created, edges: [] });
    },
    [setGraph],
  );
  const deleteEdge = useCallback(
    (edge: FlowEdge) => {
      setGraph((g) => removeItems(g, new Set(), new Set([edge.id])));
      setSelection(EMPTY_SELECTION);
      toast({ title: "Deleted the connection", action: { label: "Undo", onClick: undo } });
    },
    [setGraph, undo],
  );
  // Fit once on mount for new canvases (and always on phones); read once, never per render.
  const [fitOnMount] = useState(
    () => window.innerWidth < 640 || (initial.graph.viewport.zoom === 1 && initial.graph.viewport.x === 0 && initial.graph.viewport.y === 0),
  );

  const pick = (i: ValidationIssue) => {
    if (i.node_id && draft.graph.nodes.some((n) => n.id === i.node_id)) setSelection({ nodes: [i.node_id], edges: [] });
    else if (i.edge_id && draft.graph.edges.some((e) => e.id === i.edge_id)) setSelection({ nodes: [], edges: [i.edge_id] });
  };

  const openSettings = useCallback((s: SettingsSection) => setParams((p) => (p.set("configure", s), p), { replace: true }), [setParams]);
  const createTool = useCallback(() => openSettings("functions"), [openSettings]);
  const closeSettings = () => setParams((p) => (p.delete("configure"), p), { replace: true });
  const versionNumber = detail.published_version?.version_number;

  const sidePanel = selectedNode ? (
    <NodePanel
      node={selectedNode}
      nodes={draft.graph.nodes}
      edges={draft.graph.edges}
      setGraph={setGraph}
      issues={issues}
      catalogs={catalogs}
      allowHttp={allowHttp}
      locked={locked}
      onClose={closePanel}
      onDelete={deleteNode}
      onDuplicate={duplicateNode}
      onSelectEdge={selectEdge}
      onCreateTool={createTool}
    />
  ) : selectedEdge ? (
    <EdgePanel
      edge={selectedEdge}
      nodes={draft.graph.nodes}
      setGraph={setGraph}
      issues={issues}
      variables={variables}
      locked={locked}
      onClose={closePanel}
      onDelete={deleteEdge}
    />
  ) : (
    <Tabs
      value={tab}
      onValueChange={(v) => setTab(v as SideTab)}
      aria-label="Builder side panel"
      className="flex h-full min-h-0 flex-col [&>[role=tablist]]:px-5"
      items={[
        { value: "assistant", label: "Assistant", icon: <MessageSquareText aria-hidden /> },
        { value: "test", label: "Test", icon: <Play aria-hidden /> },
        { value: "problems", label: "Problems", icon: <ListChecks aria-hidden />, alerts: validation.result?.errors || undefined },
      ]}
    >
      <TabPanel value="assistant" className="min-h-0 flex-1 !pt-0">
        <AssistantPanel
          flowId={draft.base.id}
          revision={draft.base.revision}
          graph={draft.graph}
          dirty={draft.dirty}
          pending={proposal !== null}
          onProposal={(p) => {
            setProposal(p);
            setFitSignal((n) => n + 1);
          }}
        />
      </TabPanel>
      <TabPanel value="test" className="min-h-0 flex-1 overflow-y-auto !pt-0">
        <FlowTestPanel agentId={agent.id} dirty={dirty} errors={validation.result?.errors ?? 0} onSaveFirst={save} onStarted={events.reset} />
      </TabPanel>
      <TabPanel value="problems" className="min-h-0 flex-1 overflow-y-auto !pt-0">
        <ValidationPanel
          result={validation.result}
          graph={draft.graph}
          checking={validation.checking}
          onPick={pick}
          onRemoveEdge={(edgeId) => draft.setGraph((g) => removeItems(g, new Set(), new Set([edgeId])))}
        />
      </TabPanel>
    </Tabs>
  );

  return (
    <div className="-mb-12 flex flex-col lg:h-[calc(100dvh-60px-32px-84px)] lg:min-h-[560px]">
      <LeaveGuard when={dirty && !draft.saving} />
      <header className="mb-4 flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
        <div className="flex w-full min-w-0 flex-col gap-1.5 sm:w-auto sm:flex-1">
          <Link to="/agents" className="link-underline inline-flex w-fit items-center gap-1 rounded-inline text-[13px] text-fg-2 hover:text-fg">
            <ChevronLeft className="size-4" aria-hidden /> Agents
          </Link>
          <div className="flex min-w-0 flex-col gap-1">
            <Input
              aria-label="Flow name"
              value={draft.name}
              maxLength={80}
              onChange={(e) => draft.setName(e.target.value)}
              aria-invalid={Boolean(nameError) || undefined}
              className="-ml-2 h-10 w-full max-w-[520px] border-transparent bg-transparent px-2 font-display text-[20px] tracking-[-0.02em] shadow-none hover:border-line focus:border-line-strong sm:text-[22px]"
            />
            {nameError && (
              <p role="alert" className="flex items-center gap-1.5 text-[13px] text-danger-text">
                <CircleAlert className="size-3.5" aria-hidden /> {nameError}
              </p>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge icon={<FlowArrow weight="bold" />}>Flow</Badge>
            <button type="button" onClick={() => setHistory(true)} className="cursor-pointer rounded-full transition-transform">
              {versionNumber ? (
                <Badge tone="success" icon={<History />}>
                  Live on version {versionNumber}
                </Badge>
              ) : (
                <Badge tone="neutral" icon={<History />}>
                  Not published
                </Badge>
              )}
            </button>
            <span className="flex min-w-0 max-w-full items-center gap-0.5 rounded-inline bg-surface-2 py-0.5 pl-2 pr-0.5">
              <span className="truncate font-mono text-[12px] text-fg-3">{agent.id}</span>
              <CopyButton value={agent.id} label="Copy agent ID" className="size-6" />
            </span>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <AnimatePresence initial={false}>
            {dirty && (
              <motion.span
                initial={{ opacity: 0, x: 6 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0 }}
                className="mr-1 flex items-center gap-1.5 text-[13px] text-warning-text"
                aria-live="polite"
              >
                <span className="size-2 rounded-full bg-warning" aria-hidden /> Unsaved changes
              </motion.span>
            )}
          </AnimatePresence>
          <IconButton label="Flow settings" onClick={() => openSettings("model")} className="border border-line bg-surface">
            <Settings2 className="size-4" aria-hidden />
          </IconButton>
          <Button
            icon={<Save aria-hidden />}
            pending={draft.saving}
            disabled={!dirty || draft.saving || Boolean(nameError) || locked}
            onClick={() => void save()}
          >
            Save
          </Button>
          <Button variant="primary" icon={<Rocket aria-hidden />} onClick={() => setPublishing(true)} disabled={locked}>
            Publish
          </Button>
        </div>
      </header>

      <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-feature border border-line bg-surface shadow-2 lg:flex-row">
        <div className="relative h-[62dvh] min-h-[420px] min-w-0 lg:h-auto lg:flex-1">
          <FlowCanvas
            graph={shownGraph}
            setGraph={setGraph}
            onViewport={draft.setViewport}
            undo={draft.undo}
            redo={draft.redo}
            canUndo={draft.canUndo}
            canRedo={draft.canRedo}
            selection={selection}
            onSelect={setSelection}
            issues={issues}
            activeNodeId={events.active}
            visited={events.visited}
            diff={diff}
            locked={locked}
            onLockedAttempt={lockedNotice}
            modelLabel={modelLabel}
            fitOnMount={fitOnMount}
            fitSignal={fitSignal}
          />
          <div className="pointer-events-none absolute inset-x-0 top-3 z-10 flex justify-center sm:top-4 sm:pl-[76px]">
            <AnimatePresence>
              {proposal && diff && (
                <ProposalBar
                  proposal={proposal}
                  diff={diff}
                  onDecline={() => setProposal(null)}
                  onApprove={() => {
                    approveProposal(proposal, draft.setGraph, draft.setName);
                    setProposal(null);
                    toast({
                      tone: "success",
                      title: "Changes applied",
                      description: "Save to keep them.",
                      action: { label: "Undo", onClick: draft.undo },
                    });
                  }}
                />
              )}
            </AnimatePresence>
          </div>
        </div>
        <aside
          aria-label={selectedNode ? "Step settings" : selectedEdge ? "Connection settings" : "Assistant, test and problems"}
          className={cn("flex min-h-[420px] min-w-0 flex-col border-t border-line bg-surface lg:min-h-0 lg:w-[380px] lg:border-l lg:border-t-0")}
        >
          <AnimatePresence mode="wait" initial={false}>
            <motion.div
              key={selectedNode?.id ?? selectedEdge?.id ?? "tabs"}
              initial={{ opacity: 0, x: 10 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -6 }}
              transition={{ duration: 0.18, ease: [0.22, 1, 0.36, 1] }}
              className="flex min-h-0 flex-1 flex-col"
            >
              {sidePanel}
            </motion.div>
          </AnimatePresence>
        </aside>
      </div>

      <PublishDialog
        open={publishing}
        onOpenChange={setPublishing}
        flowId={draft.base.id}
        revision={draft.base.revision}
        validation={validation.result}
        dirty={dirty}
        onIssues={(found) => {
          validation.setResult({ errors: found.length, warnings: 0, issues: found });
          setTab("problems");
        }}
        onPublished={() => {
          void live.refetch();
          void qc.invalidateQueries({ queryKey: agentKeys.versions(agent.id) });
        }}
      />
      <GlobalSettingsDrawer
        open={configure !== null && SECTIONS.includes(configure)}
        section={configure && SECTIONS.includes(configure) ? configure : "model"}
        onSection={openSettings}
        onClose={closeSettings}
        draft={settings}
        catalogs={catalogs}
        changedKeys={changedKeys}
        start={startNode ? (startNode.config as StartConfig) : null}
        onStart={(patch) =>
          draft.setGraph((g) => ({
            ...g,
            nodes: g.nodes.map((n) =>
              n.type === "start" ? ({ ...n, config: { ...(n.config as ConfigByNode["start"]), ...patch } } as FlowNode) : n,
            ),
          }))
        }
      />
      <VersionDrawer
        open={history}
        onOpenChange={setHistory}
        agent={detail}
        revision={settings.base.revision}
        dirty={dirty}
        onRestored={(r) => {
          settings.resetTo(r.agent);
          setHistory(false);
        }}
      />
      <Dialog
        open={conflict !== null}
        onOpenChange={(o) => !o && setConflict(null)}
        icon={<RefreshCw />}
        title={conflict === "agent_draft_changed" ? "The flow settings changed somewhere else" : "This flow changed somewhere else"}
        description="It was saved in another tab or window after you opened it. Nothing of yours was saved. Load the latest version (your changes here are dropped), or keep editing and copy what you need first."
        footer={
          <>
            <Button onClick={() => setConflict(null)}>Keep editing</Button>
            <Button
              variant="primary"
              icon={<RefreshCw aria-hidden />}
              onClick={async () => {
                const [fresh, agentFresh] = await Promise.all([fetchFlowByAgent(agent.id), live.refetch()]);
                draft.resetTo(fresh);
                if (agentFresh.data) settings.resetTo(agentFresh.data);
                validation.setResult(fresh.last_validation);
                setConflict(null);
              }}
            >
              Load the latest
            </Button>
          </>
        }
      />
    </div>
  );
}

function variableNames(nodes: FlowNode[]): string[] {
  const out: string[] = [];
  for (const n of nodes) {
    if (n.type === "extract_variable") out.push(...(n.config as ConfigByNode["extract_variable"]).fields.map((f) => f.name));
    if (n.type === "task") out.push(...(n.config as ConfigByNode["task"]).fields.map((f) => `task_result.${f.name}`));
    if (n.type === "webhook") out.push(...(n.config as ConfigByNode["webhook"]).request.response_mappings.map((m) => m.variable_name));
  }
  return [...new Set(out)];
}

function BuilderSkeleton() {
  return (
    <div className="flex flex-col gap-4" aria-busy="true" aria-label="Loading flow">
      <Skeleton className="h-4 w-20" />
      <Skeleton className="h-9 w-80" />
      <Skeleton className="h-5 w-64" />
      <div className="flex gap-0 overflow-hidden rounded-feature border border-line">
        <Skeleton className="h-[62dvh] flex-1 rounded-none" />
        <Skeleton className="hidden h-[62dvh] w-[400px] rounded-none border-l border-line lg:block" />
      </div>
    </div>
  );
}
