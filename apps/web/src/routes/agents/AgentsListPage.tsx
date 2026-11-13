import { MagnifyingGlass, Robot } from "@phosphor-icons/react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ArrowUpDown,
  BrainCircuit,
  FileText,
  LayoutGrid,
  LayoutTemplate,
  Phone,
  Plus,
  Radio,
  Rows3,
  Search,
  Trash2,
  TriangleAlert,
  Volume2,
  X,
} from "lucide-react";
import { AnimatePresence } from "motion/react";
import { useState } from "react";
import { Link } from "react-router";
import {
  agentDeleted,
  type AgentSort,
  type AgentStatus,
  type AgentSummary,
  type AgentType,
  deleteAgent,
  AGENT_PAGE_SIZES,
  useAgents,
  useLlmCatalog,
  useVoiceCatalog,
} from "../../api/agents";
import { problemFor } from "../../api/errors";
import type { ProblemFor } from "../../api/types";
import { problemMessage } from "../../api/problems";
import {
  Badge,
  Button,
  Dialog,
  EmptyState,
  FlowChain,
  IconButton,
  Input,
  Menu,
  MenuContent,
  MenuRadioGroup,
  MenuRadioItem,
  MenuTrigger,
  PageHeader,
  PagerCompact,
  Pagination,
  Segmented,
  Skeleton,
  TabPanel,
  Table,
  Tabs,
  usePageSize,
  TruncatedText,
  toast,
  type Column,
} from "../../components";
import { useDebounced } from "../../lib/useDebounced";
import { AgentActions } from "./AgentActions";
import { AgentCard, WithExtras, attentionReason } from "./AgentCard";
import { DuplicateAgentDialog } from "./DuplicateAgentDialog";
import { languageLabel, llmLabel } from "./editor/catalogs";
import { agentPath, NEW_AGENT_PATH, TEMPLATES_PATH } from "../../lib/paths";
import { timeAgo } from "../../lib/format";
import { AGENT_TYPES, AgentTypeBadge } from "./agentType";

type Filter = "all" | AgentType;
type Status = "all" | AgentStatus;
type View = "cards" | "table";

const STATUSES: { value: Status; label: string; empty: string }[] = [
  { value: "all", label: "All", empty: "No agents" },
  { value: "live", label: "Live", empty: "No live agents" },
  { value: "draft", label: "Drafts", empty: "No unpublished agents" },
  { value: "attention", label: "Needs attention", empty: "Nothing needs attention" },
];
const SORTS: { value: AgentSort; label: string }[] = [
  { value: "updated", label: "Last edited" },
  { value: "created", label: "Newest" },
  { value: "name", label: "Name, A to Z" },
];
const VIEW_KEY = "callwright.agents.view";
const readView = (): View => {
  try {
    return localStorage.getItem(VIEW_KEY) === "table" ? "table" : "cards";
  } catch {
    return "cards";
  }
};

const PARTS = [
  { key: "prompt", label: "Your prompt", icon: <FileText aria-hidden /> },
  { key: "model", label: "Language model", icon: <BrainCircuit aria-hidden /> },
  { key: "voice", label: "Voice", icon: <Volume2 aria-hidden /> },
  { key: "caller", label: "Caller", icon: <Phone aria-hidden /> },
];
type Attachment = NonNullable<ProblemFor<"/agents/{agent_id}", "delete", 409>["attachments"]>[number];

/**
 * Agents list (T051, US2): status tabs with counts (all, live, drafts, needs attention), search by
 * part of a name or a full agent ID, a type filter, sort, and cards or a table for many agents.
 * Every agent has an always-visible actions menu: open, test, versions, duplicate (a dialog that
 * picks the version and names the copy) and delete with confirmation, refused with the list of
 * live attachments when a channel still uses the agent.
 */
export function AgentsListPage() {
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [status, setStatus] = useState<Status>("all");
  const [sort, setSort] = useState<AgentSort>("updated");
  const [view, setViewState] = useState<View>(readView);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = usePageSize("agents", AGENT_PAGE_SIZES);
  const q = useDebounced(search.trim(), 250);
  const agents = useAgents(q, filter === "all" ? null : filter, page, { status: status === "all" ? null : status, sort, pageSize });
  const llm = useLlmCatalog();
  const voice = useVoiceCatalog();
  const [deleting, setDeleting] = useState<AgentSummary | null>(null);
  const [inUse, setInUse] = useState<{ agent: AgentSummary; attachments: Attachment[] } | null>(null);
  const [copying, setCopying] = useState<AgentSummary | null>(null);
  const setView = (v: View) => {
    setViewState(v);
    try {
      localStorage.setItem(VIEW_KEY, v);
    } catch {
      /* private mode: the choice lasts until reload */
    }
  };

  const remove = useMutation({
    mutationFn: async (a: AgentSummary) => {
      await deleteAgent(a.id);
      return a;
    },
    onSuccess: (a) => {
      setDeleting(null);
      agentDeleted(qc, a.id);
      toast({ tone: "success", title: "Agent deleted", description: `${a.name} is gone from the list. Past calls keep their configuration.` });
    },
    onError: (e, a) => {
      setDeleting(null);
      // 409 agent_in_use lists the attachments to remove first.
      const conflict = problemFor(e, "/agents/{agent_id}", "delete", 409);
      if (conflict) setInUse({ agent: a, attachments: conflict.attachments ?? [] });
      else toast({ tone: "error", title: "Not deleted", description: problemMessage(e, "agent") });
    },
  });

  const items = agents.data?.items ?? [];
  const total = agents.data?.total ?? 0;
  const counts = agents.data?.counts;
  const filtered = q !== "" || filter !== "all" || status !== "all";
  const firstLoad = agents.isPending;
  const statusEmpty = STATUSES.find((x) => x.value === status)!.empty;
  const columns: Column<AgentSummary>[] = [
    {
      key: "name",
      header: "Agent",
      cell: (a) => (
        <div className="flex min-w-0 flex-col">
          <Link to={agentPath(a)} className="link-underline min-w-0 max-w-full self-start rounded-inline font-medium text-fg">
            <TruncatedText focusable={false}>{a.name}</TruncatedText>
          </Link>
          <TruncatedText className="font-mono text-[12px] text-fg-3">{a.id}</TruncatedText>
        </div>
      ),
    },
    {
      key: "type",
      header: "Type",
      hideOnNarrow: true,
      cell: (a) => <AgentTypeBadge type={a.type} />,
    },
    {
      key: "status",
      header: "Status",
      cell: (a) => (
        <div className="flex flex-wrap items-center gap-1.5">
          {a.published_version ? (
            <Badge tone="success" icon={<Radio />}>
              Live, v{a.published_version.version_number}
            </Badge>
          ) : (
            <Badge>Not published</Badge>
          )}
          {(a.has_publish_blockers || (a.vendor_warnings?.length ?? 0) > 0) && (
            <span title={attentionReason(a)}>
              <Badge tone="warning" icon={<TriangleAlert />}>
                Needs attention
              </Badge>
            </span>
          )}
        </div>
      ),
    },
    {
      key: "model",
      header: "Model",
      hideOnNarrow: true,
      cell: (a) => <WithExtras value={llmLabel(llm.data, a.llm_model)} extras={a.llm_extra_models?.map((m) => llmLabel(llm.data, m))} />,
    },
    { key: "speech", header: "Speech", hideOnNarrow: true, cell: (a) => <WithExtras value={a.stt_label ?? ""} extras={a.stt_extra_labels} /> },
    { key: "voice", header: "Voice", hideOnNarrow: true, cell: (a) => <WithExtras value={a.voice_label} extras={a.voice_extra_labels} /> },
    {
      key: "updated",
      header: "Last edited",
      cell: (a) => (
        <time className="whitespace-nowrap text-fg-2" dateTime={a.updated_at} title={new Date(a.updated_at).toLocaleString()}>
          {timeAgo(a.updated_at)}
        </time>
      ),
    },
    {
      key: "actions",
      header: <span className="sr-only">Actions</span>,
      width: "48px",
      align: "right",
      cell: (a) => <AgentActions agent={a} onDuplicate={() => setCopying(a)} onDelete={() => setDeleting(a)} />,
    },
  ];

  return (
    <>
      <PageHeader
        title="Agents"
        description="Prompt and flow agents with their versions, voices and models."
        actions={
          !firstLoad && total === 0 && !filtered ? undefined : (
            <>
              <Button asChild icon={<LayoutTemplate aria-hidden />}>
                <Link to={TEMPLATES_PATH}>Templates</Link>
              </Button>
              <Button asChild variant="primary" icon={<Plus aria-hidden />}>
                <Link to={NEW_AGENT_PATH}>New agent</Link>
              </Button>
            </>
          )
        }
      />

      {!firstLoad && total === 0 && !filtered ? (
        <section className="relative overflow-hidden rounded-feature border border-line bg-surface shadow-2">
          <div className="relative grid gap-8 px-6 py-10 sm:px-10 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] lg:items-center">
            <EmptyState
              className="px-0 py-0"
              icon={<Robot weight="duotone" />}
              title="Create your first agent"
              actions={
                <>
                  <Button asChild variant="primary" icon={<Plus aria-hidden />}>
                    <Link to={NEW_AGENT_PATH}>New agent</Link>
                  </Button>
                  <Button asChild icon={<LayoutTemplate aria-hidden />}>
                    <Link to={TEMPLATES_PATH}>Start from a template</Link>
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
          <div className="mb-4 flex flex-col gap-3 md:flex-row md:items-center">
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
                { value: "all", label: "All types" },
                ...(["single_prompt", "flow"] as const).map((type) => {
                  const { label, icon: Icon } = AGENT_TYPES[type];
                  return { value: type, label, icon: <Icon aria-hidden /> };
                }),
              ]}
            />
            <div className="flex flex-wrap items-center gap-2 md:ml-auto">
              {agents.data && (
                <PagerCompact
                  page={page}
                  totalPages={agents.data.total_pages}
                  total={total}
                  pageSize={pageSize}
                  onPageChange={setPage}
                  className="mr-1"
                />
              )}
              <Menu>
                <MenuTrigger asChild>
                  <Button size="sm" variant="ghost" icon={<ArrowUpDown aria-hidden />}>
                    <span className="sr-only">Sort: </span>
                    {SORTS.find((x) => x.value === sort)!.label}
                  </Button>
                </MenuTrigger>
                <MenuContent>
                  <MenuRadioGroup
                    value={sort}
                    onValueChange={(v) => {
                      setSort(v as AgentSort);
                      setPage(1);
                    }}
                  >
                    {SORTS.map((x) => (
                      <MenuRadioItem key={x.value} value={x.value}>
                        {x.label}
                      </MenuRadioItem>
                    ))}
                  </MenuRadioGroup>
                </MenuContent>
              </Menu>
              <Segmented
                aria-label="View"
                size="sm"
                value={view}
                onValueChange={setView}
                options={[
                  { value: "cards", label: <span className="sr-only">Cards</span>, icon: <LayoutGrid aria-hidden /> },
                  { value: "table", label: <span className="sr-only">Table</span>, icon: <Rows3 aria-hidden /> },
                ]}
              />
            </div>
          </div>

          <Tabs
            aria-label="Agent status"
            value={status}
            onValueChange={(v) => {
              setStatus(v as Status);
              setPage(1);
            }}
            items={STATUSES.map((x) => ({ value: x.value, label: x.label, count: counts?.[x.value] }))}
          >
            <TabPanel value={status} className="pt-4">
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
                  title={q ? `No agents match "${q}"` : filter !== "all" ? "No agents of this type" : statusEmpty}
                  actions={
                    <Button
                      onClick={() => {
                        setSearch("");
                        setFilter("all");
                        setStatus("all");
                      }}
                    >
                      Show all agents
                    </Button>
                  }
                >
                  Search matches part of a name, or a full agent ID such as agt_01JB...
                </EmptyState>
              ) : (
                <div className={agents.isPlaceholderData ? "opacity-60 transition-opacity" : "transition-opacity"}>
                  {view === "table" ? (
                    <div className="overflow-hidden rounded-panel border border-line bg-surface shadow-1">
                      <Table caption="Agents" columns={columns} rows={items} rowKey={(a) => a.id} />
                    </div>
                  ) : (
                    <div className="grid grid-cols-[minmax(0,1fr)] gap-4 md:grid-cols-2 xl:grid-cols-3">
                      <AnimatePresence>
                        {items.map((a) => (
                          <AgentCard
                            key={a.id}
                            agent={a}
                            modelLabel={llmLabel(llm.data, a.llm_model)}
                            modelExtras={a.llm_extra_models?.map((m) => llmLabel(llm.data, m))}
                            languageLabel={languageLabel(voice.data, a.language)}
                            onDuplicate={() => setCopying(a)}
                            onDelete={() => setDeleting(a)}
                          />
                        ))}
                      </AnimatePresence>
                    </div>
                  )}
                  {agents.data && total > AGENT_PAGE_SIZES[0] && (
                    <Pagination
                      className="mt-4 px-0"
                      page={page}
                      totalPages={agents.data.total_pages}
                      total={total}
                      pageSize={pageSize}
                      pageSizes={AGENT_PAGE_SIZES}
                      noun="agents"
                      onPageChange={setPage}
                      onPageSizeChange={(n) => {
                        setPageSize(n);
                        setPage(1);
                      }}
                    />
                  )}
                </div>
              )}
            </TabPanel>
          </Tabs>
        </>
      )}

      <DuplicateAgentDialog open={copying !== null} onOpenChange={(o) => !o && setCopying(null)} agent={copying} />
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
