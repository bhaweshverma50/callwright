import { MagnifyingGlass, Robot } from "@phosphor-icons/react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { BrainCircuit, FileText, LayoutTemplate, MessageSquareText, Phone, Volume2, Plus, Search, Trash2, Workflow, X } from "lucide-react";
import { AnimatePresence } from "motion/react";
import { useRef, useState } from "react";
import { Link, useNavigate } from "react-router";
import {
  agentKeys,
  idempotencyKey,
  PAGE_SIZE,
  useAgents,
  useLlmCatalog,
  useVoiceCatalog,
  type AgentDetail,
  type AgentSummary,
  type AgentType,
} from "../../api/agents";
import { api } from "../../api/client";
import { ApiError, toProblem } from "../../api/errors";
import { problemMessage } from "../../api/problems";
import { Button, Dialog, EmptyState, FlowChain, IconButton, Input, PageHeader, Pagination, Segmented, Skeleton, toast } from "../../components";
import { useDebounced } from "../../lib/useDebounced";
import { AgentCard } from "./AgentCard";
import { languageLabel, llmLabel } from "./editor/catalogs";

type Filter = "all" | AgentType;

const PARTS = [
  { key: "prompt", label: "Your prompt", icon: <FileText aria-hidden /> },
  { key: "model", label: "Language model", icon: <BrainCircuit aria-hidden /> },
  { key: "voice", label: "Voice", icon: <Volume2 aria-hidden /> },
  { key: "caller", label: "Caller", icon: <Phone aria-hidden /> },
];
interface Attachment {
  kind: string;
  id: string;
  label: string;
}

/**
 * Agents list (T051, US2): newest-updated first, search by part of a name or a full agent ID, a
 * type filter, duplicate (no confirmation, one copy per click, FR-038) and delete with
 * confirmation, refused with the list of live attachments when a channel still uses the agent.
 */
export function AgentsListPage() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [page, setPage] = useState(1);
  const q = useDebounced(search.trim(), 250);
  const agents = useAgents(q, filter === "all" ? null : filter, page);
  const llm = useLlmCatalog();
  const voice = useVoiceCatalog();
  const [deleting, setDeleting] = useState<AgentSummary | null>(null);
  const [inUse, setInUse] = useState<{ agent: AgentSummary; attachments: Attachment[] } | null>(null);
  const [fresh, setFresh] = useState<string | null>(null);
  const dupKeys = useRef(new Map<string, string>());

  const duplicate = useMutation({
    mutationFn: async (a: AgentSummary) => {
      // One key per agent until the copy exists, so repeated clicks create one copy.
      const key = dupKeys.current.get(a.id) ?? idempotencyKey();
      dupKeys.current.set(a.id, key);
      const { data, error, response } = await api.POST("/agents/{agent_id}/duplicate", {
        params: { path: { agent_id: a.id }, header: { "Idempotency-Key": key } },
        body: {},
      });
      if (!response.ok) throw new ApiError(response.status, toProblem(response.status, error));
      return { copy: data as AgentDetail, from: a };
    },
    onSuccess: ({ copy, from }) => {
      dupKeys.current.delete(from.id);
      setFresh(copy.id);
      window.setTimeout(() => setFresh((f) => (f === copy.id ? null : f)), 2400);
      void qc.invalidateQueries({ queryKey: ["agents", "list"] });
      toast({
        tone: "success",
        title: "Agent duplicated",
        description: `${copy.name} starts at version 1 and is not published.`,
        action: { label: "Open the copy", onClick: () => navigate(`/agents/${copy.id}/edit`) },
      });
    },
    onError: (e) => toast({ tone: "error", title: "Not duplicated", description: problemMessage(e, "agent") }),
  });

  const remove = useMutation({
    mutationFn: async (a: AgentSummary) => {
      const { error, response } = await api.DELETE("/agents/{agent_id}", { params: { path: { agent_id: a.id } } });
      if (!response.ok) throw new ApiError(response.status, toProblem(response.status, error));
      return a;
    },
    onSuccess: (a) => {
      setDeleting(null);
      qc.setQueriesData<{ items: AgentSummary[]; total: number }>({ queryKey: ["agents", "list"] }, (old) =>
        old ? { ...old, items: old.items.filter((x) => x.id !== a.id), total: Math.max(0, old.total - 1) } : old,
      );
      qc.removeQueries({ queryKey: agentKeys.detail(a.id) });
      void qc.invalidateQueries({ queryKey: ["agents", "list"] });
      toast({ tone: "success", title: "Agent deleted", description: `${a.name} is gone from the list. Past calls keep their configuration.` });
    },
    onError: (e, a) => {
      setDeleting(null);
      if (e instanceof ApiError && e.status === 409) {
        const attachments = ((e.problem as unknown as { attachments?: Attachment[] }).attachments ?? []) as Attachment[];
        setInUse({ agent: a, attachments });
      } else toast({ tone: "error", title: "Not deleted", description: problemMessage(e, "agent") });
    },
  });

  const items = agents.data?.items ?? [];
  const total = agents.data?.total ?? 0;
  const filtered = q !== "" || filter !== "all";
  const firstLoad = agents.isPending;

  return (
    <>
      <PageHeader
        title="Agents"
        description="Prompt and flow agents with their versions, voices and models."
        actions={
          !firstLoad && total === 0 && !filtered ? undefined : (
            <>
              <Button asChild icon={<LayoutTemplate aria-hidden />}>
                <Link to="/agents/templates">Templates</Link>
              </Button>
              <Button asChild variant="primary" icon={<Plus aria-hidden />}>
                <Link to="/agents/new">New agent</Link>
              </Button>
            </>
          )
        }
      />

      {!firstLoad && total === 0 && !filtered ? (
        <section className="relative overflow-hidden rounded-feature border border-line bg-surface shadow-2">
          <div aria-hidden className="glow-backdrop pointer-events-none absolute inset-0 opacity-70" />
          <div className="relative grid gap-8 px-6 py-10 sm:px-10 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] lg:items-center">
            <EmptyState
              className="px-0 py-0"
              icon={<Robot weight="duotone" />}
              title="Create your first agent"
              actions={
                <>
                  <Button asChild variant="primary" icon={<Plus aria-hidden />}>
                    <Link to="/agents/new">New agent</Link>
                  </Button>
                  <Button asChild icon={<LayoutTemplate aria-hidden />}>
                    <Link to="/agents/templates">Start from a template</Link>
                  </Button>
                </>
              }
            >
              An agent answers or places calls with your prompt, a language model and a voice. Start from scratch, or pick one of seven industry
              templates and adjust it.
            </EmptyState>
            <div className="rounded-panel border border-line bg-surface-2/70 px-5 py-6">
              <p className="text-[13px] font-medium text-fg">What an agent is made of</p>
              <FlowChain label="Parts of an agent" nodes={PARTS} active="prompt" flow stack="tight" className="mt-5" />
              <p className="mt-5 text-[13px] leading-relaxed text-fg-2">
                You write the prompt; you choose the model and the voice. Each part shows its price per minute while you build.
              </p>
            </div>
          </div>
        </section>
      ) : (
        <>
          <div className="mb-5 flex flex-col gap-3 md:flex-row md:items-center">
            <Input
              className="min-w-0 md:w-[340px]"
              prefix={<Search aria-hidden />}
              placeholder="Search by name or agent ID"
              aria-label="Search agents by name or agent ID"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setPage(1);
              }}
              suffix={
                search ? (
                  <IconButton label="Clear search" className="size-6 [&_svg]:size-3.5" onClick={() => setSearch("")}>
                    <X aria-hidden />
                  </IconButton>
                ) : undefined
              }
            />
            <Segmented
              aria-label="Agent type"
              value={filter}
              onValueChange={(v) => {
                setFilter(v);
                setPage(1);
              }}
              options={[
                { value: "all", label: "All" },
                { value: "single_prompt", label: "Single prompt", icon: <MessageSquareText aria-hidden /> },
                { value: "flow", label: "Flow", icon: <Workflow aria-hidden /> },
              ]}
            />
            <p className="text-[12.5px] text-fg-3 md:ml-auto" aria-live="polite">
              {firstLoad ? "" : `${total.toLocaleString()} ${total === 1 ? "agent" : "agents"}${filtered ? " found" : ""}`}
            </p>
          </div>

          {firstLoad ? (
            <div className="grid grid-cols-[minmax(0,1fr)] gap-4 md:grid-cols-2 xl:grid-cols-3" aria-busy="true" aria-label="Loading agents">
              {Array.from({ length: 6 }, (_, i) => (
                <Skeleton key={i} className="h-[214px] w-full rounded-panel" />
              ))}
            </div>
          ) : agents.isError ? (
            <EmptyState icon={<Robot weight="duotone" />} title="Agents did not load">
              {problemMessage(agents.error, "agent")}
            </EmptyState>
          ) : items.length === 0 ? (
            <EmptyState
              icon={<MagnifyingGlass weight="duotone" />}
              title={q ? `No agents match "${q}"` : "No agents of this type"}
              actions={
                <Button
                  onClick={() => {
                    setSearch("");
                    setFilter("all");
                  }}
                >
                  Clear search and filter
                </Button>
              }
            >
              Search matches part of a name, or a full agent ID such as agt_01JB...
            </EmptyState>
          ) : (
            <div className={agents.isPlaceholderData ? "opacity-60 transition-opacity" : "transition-opacity"}>
              <div className="grid grid-cols-[minmax(0,1fr)] gap-4 md:grid-cols-2 xl:grid-cols-3">
                <AnimatePresence>
                  {items.map((a) => (
                    <AgentCard
                      key={a.id}
                      agent={a}
                      fresh={fresh === a.id}
                      modelLabel={llmLabel(llm.data, a.llm_model)}
                      languageLabel={languageLabel(voice.data, a.language)}
                      duplicating={duplicate.isPending && duplicate.variables?.id === a.id}
                      onDuplicate={() => !duplicate.isPending && duplicate.mutate(a)}
                      onDelete={() => setDeleting(a)}
                    />
                  ))}
                </AnimatePresence>
              </div>
              {agents.data && agents.data.total_pages > 1 && (
                <Pagination
                  className="mt-4 px-0"
                  page={page}
                  totalPages={agents.data.total_pages}
                  total={total}
                  pageSize={PAGE_SIZE}
                  noun="agents"
                  onPageChange={setPage}
                />
              )}
            </div>
          )}
        </>
      )}

      <Dialog
        open={deleting !== null}
        onOpenChange={(o) => !o && !remove.isPending && setDeleting(null)}
        role="alertdialog"
        size="sm"
        icon={<Trash2 />}
        title={`Delete ${deleting?.name ?? "agent"}?`}
        description="The agent leaves the list and can no longer take calls. Past calls keep their transcripts and the configuration they ran with."
        footer={
          <>
            <Button autoFocus onClick={() => setDeleting(null)} disabled={remove.isPending}>
              Cancel
            </Button>
            <Button variant="danger" pending={remove.isPending} onClick={() => deleting && remove.mutate(deleting)}>
              Delete agent
            </Button>
          </>
        }
      />
      <Dialog
        open={inUse !== null}
        onOpenChange={(o) => !o && setInUse(null)}
        size="sm"
        icon={<Phone />}
        title={`${inUse?.agent.name ?? "This agent"} is still taking calls`}
        description="Detach it from these first, then delete it."
        footer={<Button onClick={() => setInUse(null)}>Close</Button>}
      >
        <ul className="flex flex-col gap-2">
          {inUse?.attachments.map((a) => (
            <li key={a.id} className="flex items-center gap-2.5 rounded-control bg-surface-2/70 px-3 py-2">
              <Phone className="size-4 text-fg-3" aria-hidden />
              <span className="font-mono text-[13px] text-fg tnum">{a.label}</span>
              <span className="ml-auto text-[12px] text-fg-3">
                {a.kind === "phone_number" ? "Phone number" : a.kind === "whatsapp_channel" ? "WhatsApp" : "Outbound campaign"}
              </span>
            </li>
          ))}
        </ul>
      </Dialog>
    </>
  );
}
