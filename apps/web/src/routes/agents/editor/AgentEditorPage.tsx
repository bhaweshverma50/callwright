import { Robot, FlowArrow } from "@phosphor-icons/react";
import { ChevronLeft, CircleDot, History, MessageSquareText, Play, RefreshCw, Save, Undo2 } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { useAgent, useAgentDefaults, useLlmCatalog, useVoiceCatalog, type AgentDetail, type ConfigIssue } from "../../../api/agents";
import { isApiError } from "../../../api/errors";
import { problemMessage } from "../../../api/problems";
import {
  Badge,
  Button,
  CopyButton,
  Dialog,
  EmptyState,
  ErrorSummaryDialog,
  Input,
  LeaveGuard,
  Skeleton,
  TabPanel,
  Tabs,
  TruncatedText,
  WorkLayout,
  cn,
  focusRing,
  toast,
  type ErrorSummaryItem,
} from "../../../components";
import { RecordNotFound } from "../../NotFound";
import { PublishButton } from "../versions/PublishButton";
import { VersionDrawer } from "../versions/VersionDrawer";
import { labelFor } from "../versions/versionLabels";
import { AdvancedSection } from "./AdvancedSection";
import { AssistantPanel } from "./AssistantPanel";
import { BasicSection } from "./BasicSection";
import { CallBehaviorSection } from "./CallBehaviorSection";
import type { Catalogs } from "./catalogs";
import { ChecksCard } from "./ChecksCard";
import { CostCard } from "./CostCard";
import { EDITOR_PANELS } from "./panels";
import { useAgentDraft, type DraftBase } from "./useAgentDraft";
import { VoiceSection } from "./VoiceSection";
import { agentEditPath, agentFlowPath, agentTestingPath, isAgentId } from "../../../lib/paths";
import { type EditorSection, fieldId, sectionOf } from "../config/fields";

/**
 * Single-prompt agent editor (T039), at /agents/new/single (never saved) and /agents/:id/edit.
 * Loads the agent or the platform defaults plus both catalogs, then hands a ready draft to the
 * editor. Flow agents get a pointer to the flow builder instead (US1.8).
 */
export function AgentEditorPage() {
  const { id } = useParams();
  const isNew = !id;
  const valid = isNew || isAgentId(id);
  const agent = useAgent(valid && !isNew ? id : undefined);
  const defaults = useAgentDefaults("en-US", isNew);
  const llm = useLlmCatalog();
  const voice = useVoiceCatalog();

  if (!valid) return <RecordNotFound kind="agent" backTo="/agents" backLabel="Back to Agents" />;
  const failed = agent.error ?? defaults.error ?? llm.error ?? voice.error;
  if (failed) {
    if (isApiError(failed) && failed.status === 404) return <RecordNotFound kind="agent" backTo="/agents" backLabel="Back to Agents" />;
    return (
      <EmptyState icon={<Robot weight="duotone" />} title="The agent did not load">
        {problemMessage(failed, "agent")}
      </EmptyState>
    );
  }
  const ready = llm.data && voice.data && (isNew ? defaults.data : agent.data);
  if (!ready) return <EditorSkeleton />;
  if (!isNew && agent.data!.type === "flow") return <FlowAgentNotice agent={agent.data!} />;

  const initial: DraftBase = isNew
    ? { id: null, name: "", config: defaults.data!, revision: 0, detail: null }
    : { id: agent.data!.id, name: agent.data!.name, config: agent.data!.draft_config, revision: agent.data!.draft_revision, detail: agent.data! };
  return <Editor key={id ?? "new"} initial={initial} catalogs={{ llm: llm.data!, voice: voice.data! }} />;
}

type Tab = EditorSection | string;

function Editor({ initial, catalogs }: { initial: DraftBase; catalogs: Catalogs }) {
  const draft = useAgentDraft(initial, "single_prompt");
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as Tab) ?? "basics";
  const setTab = useCallback(
    (t: Tab) => setParams((p) => (t === "basics" ? (p.delete("tab"), p) : (p.set("tab", t), p)), { replace: true }),
    [setParams],
  );
  const live = useAgent(draft.base.id ?? undefined);
  const detail: AgentDetail | null = live.data ?? draft.base.detail;
  const [summary, setSummary] = useState<ConfigIssue[] | null>(null);
  const [conflict, setConflict] = useState(false);
  const [saving, setSaving] = useState<"save" | "test" | null>(null);
  // Deep links: ?history=1 opens the versions (from the agents list menu); ?describe= opens the
  // assistant with the description typed on the New agent page, sent as the first message.
  const [describe] = useState(() => params.get("describe")?.slice(0, 2000) || null);
  const [history, setHistory] = useState(() => params.get("history") === "1");
  const [assistant, setAssistant] = useState(describe !== null);
  useEffect(() => {
    if (params.has("describe") || params.has("history")) setParams((p) => (p.delete("describe"), p.delete("history"), p), { replace: true });
  }, [params, setParams]);
  const [note, setNote] = useState("");
  const [goTo, setGoTo] = useState<string | null>(null);

  // Navigate only after the saved state has rendered, so the leave guard sees a clean form.
  useEffect(() => {
    if (goTo && !draft.dirty) {
      navigate(goTo, { replace: goTo.endsWith("/edit") });
      setGoTo(null);
    }
  }, [goTo, draft.dirty, navigate]);

  const jump = useCallback(
    (pointer: string) => {
      setTab(sectionOf(pointer));
      window.setTimeout(() => {
        const el = document.getElementById(fieldId(pointer));
        el?.scrollIntoView({ block: "center", behavior: "smooth" });
        el?.focus({ preventScroll: true });
      }, 120);
    },
    [setTab],
  );

  const save = useCallback(
    async (then?: "test") => {
      setSaving(then ?? "save");
      const out = await draft.save(note);
      setSaving(null);
      if (out.status === "invalid") {
        setSummary(out.issues);
        return;
      }
      if (out.status === "conflict") return setConflict(true);
      if (out.status === "error") return void toast({ tone: "error", title: "Not saved", description: problemMessage(out.error, "agent") });
      setNote("");
      const first = !initial.id && !draft.base.id;
      toast({
        tone: "success",
        title: out.created ? (first ? "Agent created" : `Saved as version ${out.versionNumber}`) : "Saved",
        description: out.created
          ? first
            ? `${out.detail.name} is saved as version 1.`
            : undefined
          : "Nothing in the configuration changed, so no new version was recorded.",
      });
      if (then === "test") setGoTo(agentTestingPath(out.detail.id));
      else if (!draft.base.id) setGoTo(agentEditPath(out.detail.id));
    },
    [draft, note, initial.id],
  );

  // Cmd or Ctrl + S saves.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "s") {
        e.preventDefault();
        if (!saving) void save();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [save, saving]);

  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const i of draft.issues) {
      if (!draft.submitted && !draft.errorFor(i.pointer)) continue;
      const s = sectionOf(i.pointer);
      c[s] = (c[s] ?? 0) + 1;
    }
    return c;
  }, [draft]);

  const isNew = !draft.base.id;
  const title = draft.name.trim() || (isNew ? "New agent" : draft.base.name);
  const blockers = draft.validation?.publish_blockers ?? [];

  // Short labels and no icons keep seven tabs readable; Advanced goes last, where people look for it.
  const tabs = [
    { value: "basics", label: "Basics", alerts: counts.basics },
    { value: "voice", label: "Voice", alerts: counts.voice },
    { value: "behaviour", label: "Behaviour", alerts: counts.behaviour },
    ...EDITOR_PANELS.map((p) => ({ value: p.id, label: p.label })),
    { value: "advanced", label: "Advanced", alerts: counts.advanced },
  ];

  return (
    <div className="flex flex-col">
      <LeaveGuard when={draft.dirty && saving === null && goTo === null} />
      <Link to="/agents" className="link-underline mb-4 inline-flex w-fit items-center gap-1 rounded-inline text-[13px] text-fg-2 hover:text-fg">
        <ChevronLeft className="size-4" aria-hidden /> Agents
      </Link>

      <header className="mb-6 flex flex-wrap items-end justify-between gap-x-6 gap-y-4">
        <div className="flex min-w-0 flex-col gap-2">
          <h1 className="min-w-0 max-w-full font-display text-[22px] leading-tight tracking-[-0.02em] text-fg sm:text-[26px]">
            <TruncatedText>{title}</TruncatedText>
          </h1>
          <div className="flex flex-wrap items-center gap-2">
            <Badge icon={<MessageSquareText />}>Single prompt</Badge>
            {isNew ? (
              <Badge tone="warning" icon={<CircleDot />}>
                Not saved yet
              </Badge>
            ) : (
              <>
                <Badge tone="accent">Version {detail?.draft_version.version_number}</Badge>
                {!detail?.published_version && <Badge tone="neutral">Not published</Badge>}
                {detail?.published_version && detail.published_version.id !== detail.draft_version.id && (
                  <Badge tone="success">Live on version {detail.published_version.version_number}</Badge>
                )}
              </>
            )}
            {draft.base.id && (
              <span className="flex items-center gap-0.5 rounded-inline bg-surface-2 py-0.5 pl-2 pr-0.5">
                <span className="font-mono text-[12px] text-fg-3">{draft.base.id}</span>
                <CopyButton value={draft.base.id} label="Copy agent ID" className="size-6" />
              </span>
            )}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {!isNew && (
            <Button icon={<History aria-hidden />} onClick={() => setHistory(true)}>
              History
            </Button>
          )}
          <Button
            icon={<Play aria-hidden />}
            pending={saving === "test"}
            disabled={saving === "save"}
            onClick={() => (draft.dirty || !draft.base.id ? void save("test") : navigate(agentTestingPath(draft.base.id)))}
          >
            Test agent
          </Button>
          {!isNew && detail && (
            <PublishButton
              agentId={detail.id}
              draftVersion={detail.draft_version}
              published={detail.published_version}
              dirty={draft.dirty}
              blocked={blockers.length > 0}
            />
          )}
        </div>
      </header>

      <WorkLayout
        main={
          <Tabs value={tab} onValueChange={setTab} items={tabs} density="compact" aria-label="Agent settings">
            <TabPanel value="basics">
              <BasicSection draft={draft} catalogs={catalogs} onOpenAssistant={() => setAssistant(true)} />
            </TabPanel>
            <TabPanel value="voice">
              <VoiceSection draft={draft} catalogs={catalogs} />
            </TabPanel>
            <TabPanel value="behaviour">
              <CallBehaviorSection draft={draft} catalogs={catalogs} />
            </TabPanel>
            <TabPanel value="advanced">
              <AdvancedSection draft={draft} catalogs={catalogs} />
            </TabPanel>
            {EDITOR_PANELS.map((p) => (
              <TabPanel key={p.id} value={p.id}>
                <p.component agentId={draft.base.id} agentType="single_prompt" config={draft.config} update={draft.update} />
              </TabPanel>
            ))}
          </Tabs>
        }
        inspector={
          <>
            <CostCard config={draft.config} llm={catalogs.llm} voice={catalogs.voice} />
            <ChecksCard blockers={blockers} warnings={draft.validation?.warnings ?? []} loading={!draft.validation} onJump={jump} />
          </>
        }
      />

      <SaveBar
        dirty={draft.dirty}
        isNew={isNew}
        checking={draft.checking}
        saving={saving === "save"}
        disabled={saving !== null}
        note={note}
        onNote={setNote}
        onDiscard={draft.discard}
        onSave={() => void save()}
        versionNumber={detail?.draft_version.version_number}
      />

      <ErrorSummaryDialog
        open={summary !== null}
        onOpenChange={(o) => !o && setSummary(null)}
        title={isNew ? "Fix these before creating the agent" : "Fix these before saving"}
        items={(summary ?? []).map((i): ErrorSummaryItem => ({ label: labelFor(i.pointer), message: i.message, targetId: fieldId(i.pointer) }))}
        onJump={(it) => {
          const issue = summary?.find((i) => fieldId(i.pointer) === it.targetId);
          if (issue) setTab(sectionOf(issue.pointer));
        }}
      />
      <Dialog
        open={conflict}
        onOpenChange={setConflict}
        icon={<RefreshCw />}
        title="This agent changed somewhere else"
        description="Someone saved it in another tab or window after you opened it. Load the latest draft (your changes here are dropped), or keep editing and copy what you need first."
        footer={
          <>
            <Button onClick={() => setConflict(false)}>Keep editing</Button>
            <Button
              variant="primary"
              icon={<RefreshCw aria-hidden />}
              onClick={async () => {
                const r = await live.refetch();
                if (r.data) draft.resetTo(r.data);
                setConflict(false);
              }}
            >
              Load the latest
            </Button>
          </>
        }
      />
      {detail && (
        <VersionDrawer
          open={history}
          onOpenChange={setHistory}
          agent={detail}
          revision={draft.base.revision}
          dirty={draft.dirty}
          onRestored={(r) => {
            draft.resetTo(r.agent);
            setHistory(false);
          }}
        />
      )}
      <AssistantPanel open={assistant} onOpenChange={setAssistant} draft={draft} agentId={draft.base.id} initialMessage={describe} />
    </div>
  );
}

function SaveBar({
  dirty,
  isNew,
  checking,
  saving,
  disabled,
  note,
  onNote,
  onDiscard,
  onSave,
  versionNumber,
}: {
  dirty: boolean;
  isNew: boolean;
  checking: boolean;
  saving: boolean;
  disabled: boolean;
  note: string;
  onNote: (v: string) => void;
  onDiscard: () => void;
  onSave: () => void;
  versionNumber?: number;
}) {
  // Save leaves the bar once the form is clean; a keyboard user who pressed it lands on the
  // status ("All changes saved") instead of the page body.
  const statusRef = useRef<HTMLSpanElement>(null);
  const saveFocused = useRef(false);
  useEffect(() => {
    if (dirty || isNew || !saveFocused.current) return;
    saveFocused.current = false;
    if (document.activeElement === document.body) statusRef.current?.focus();
  }, [dirty, isNew]);
  let status: ReactNode;
  if (isNew) status = <span className="text-warning-text">Not saved yet</span>;
  else if (dirty) status = <span className="text-warning-text">Unsaved changes</span>;
  else status = <span className="text-fg-3">All changes saved{versionNumber ? ` in version ${versionNumber}` : ""}</span>;
  return (
    <div className="sticky bottom-0 z-20 -mx-4 mt-6 border-t border-line bg-bg/85 px-4 py-3 backdrop-blur-md sm:-mx-6 sm:px-6 lg:-mx-10 lg:px-10">
      <div className="flex flex-wrap items-center gap-3">
        <span ref={statusRef} tabIndex={-1} className={cn("flex items-center gap-2 rounded-inline text-[13px]", focusRing)} aria-live="polite">
          <AnimatePresence initial={false} mode="wait">
            <motion.span
              key={isNew ? "new" : dirty ? "dirty" : "clean"}
              initial={{ scale: 0.6, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.6, opacity: 0 }}
              className={cn("size-2 rounded-full", isNew || dirty ? "bg-warning" : "bg-success")}
              aria-hidden
            />
          </AnimatePresence>
          {status}
        </span>
        {/* Nothing to save: the bar only reports the state. Buttons stop short of the assistant dock's
            corner (sm:mr-52) so they stay clickable before the dock is moved. */}
        <div className="ml-auto flex w-full flex-wrap items-center justify-end gap-2 sm:mr-52 sm:w-auto">
          {!isNew && dirty && (
            <Input
              inputSize="md"
              className="min-w-0 flex-1 sm:w-[280px] sm:flex-none"
              placeholder="Note for this version (optional)"
              aria-label="Note for this version"
              maxLength={500}
              value={note}
              onChange={(e) => onNote(e.target.value)}
            />
          )}
          {!isNew && dirty && (
            <Button variant="ghost" icon={<Undo2 aria-hidden />} disabled={disabled} onClick={onDiscard}>
              Discard
            </Button>
          )}
          {(isNew || dirty) && (
            <Button
              variant="primary"
              icon={<Save aria-hidden />}
              pending={saving}
              disabled={(disabled && !saving) || (!dirty && !isNew)}
              onClick={(e) => {
                saveFocused.current = document.activeElement === e.currentTarget;
                onSave();
              }}
              aria-describedby={checking ? "save-checking" : undefined}
            >
              {isNew ? "Create agent" : "Save"}
            </Button>
          )}
          {checking && (
            <span id="save-checking" className="sr-only">
              Checking the configuration
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

function EditorSkeleton() {
  return (
    <div className="flex flex-col" aria-busy="true" aria-label="Loading agent">
      <Skeleton className="mb-4 h-4 w-20" />
      <Skeleton className="mb-3 h-8 w-72" />
      <Skeleton className="mb-7 h-5 w-56" />
      <WorkLayout
        main={
          <div className="flex flex-col gap-5">
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-[340px] w-full rounded-panel" />
            <Skeleton className="h-[260px] w-full rounded-panel" />
          </div>
        }
        inspector={
          <>
            <Skeleton className="h-[380px] w-full rounded-panel" />
            <Skeleton className="h-[140px] w-full rounded-panel" />
          </>
        }
      />
    </div>
  );
}

function FlowAgentNotice({ agent }: { agent: AgentDetail }) {
  return (
    <div className="flex flex-col">
      <Link to="/agents" className="link-underline mb-4 inline-flex w-fit items-center gap-1 rounded-inline text-[13px] text-fg-2 hover:text-fg">
        <ChevronLeft className="size-4" aria-hidden /> Agents
      </Link>
      <EmptyState
        icon={<FlowArrow weight="duotone" />}
        title={`${agent.name} is a flow agent`}
        actions={
          <Button asChild variant="primary" icon={<FlowArrow aria-hidden />}>
            <Link to={agentFlowPath(agent.id)}>Open the flow builder</Link>
          </Button>
        }
      >
        Flow agents are built on a canvas of steps, not a single prompt, and the type cannot change after creation. Open it in the flow builder to
        edit it.
      </EmptyState>
    </div>
  );
}
