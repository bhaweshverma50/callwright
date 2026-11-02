/**
 * Testing tab (spec 008 US1, T038): the agent's single-turn test cases with a category filter and
 * last-status chips, ways to add cases (write, generate, import), and runs judged by an LLM. When
 * the agent cannot answer a caller yet (no prompt, or a flow with no agent node), running is off
 * and the message links to the editor.
 */
import { ClipboardText } from "@phosphor-icons/react";
import { useQueryClient } from "@tanstack/react-query";
import { Download, FileDown, MoreHorizontal, Pencil, Play, Plus, Sparkles, Trash2, Upload } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router";
import type { AgentDetail } from "../../../api/agents";
import { useFlowByAgent } from "../../../api/flows";
import { downloadJson, isRetryable, useActionKey } from "../../../api/paid";
import {
  CASES_PAGE_SIZE,
  deleteTestCase,
  exportTestCases,
  startTestRun,
  testingKeys,
  useTestCases,
  useTestCategories,
  useTestRuns,
  type TestCase,
  type TestTarget,
} from "../../../api/testing";
import {
  Button,
  ConfirmDialog,
  EmptyState,
  IconButton,
  Menu,
  MenuContent,
  MenuItem,
  MenuTrigger,
  Pagination,
  Select,
  Skeleton,
  toast,
} from "../../../components";
import { FormAlert } from "../../public/FormAlert";
import { Checkbox, ProblemAlert, plural, problemText } from "../../simulations/shared";
import { ALL_CATEGORIES, CategoryLabel, TestStatusBadge, categoryOptions } from "./categories";
import { GenerateDialog } from "./GenerateDialog";
import { ImportDialog } from "./ImportDialog";
import { TestCaseEditor } from "./TestCaseEditor";
import { TestRunPanel } from "./TestRunPanel";

type Editing = { mode: "new" } | { mode: "edit"; tc: TestCase } | null;

/** Why the agent cannot run test cases yet, or null when it can. */
function useNotRunnable(agent: AgentDetail): string | null {
  const flow = useFlowByAgent(agent.type === "flow" ? agent.id : undefined);
  if (agent.type === "single_prompt")
    return agent.draft_config.prompt?.trim() ? null : "This agent has no prompt yet. Write one before running tests.";
  const nodes = flow.data?.graph?.nodes;
  if (!nodes) return null;
  return nodes.some((n) => n.type === "agent" || n.type === "task")
    ? null
    : "This flow has no agent node yet, so nothing can answer the caller. Add one before running tests.";
}

export function TestCasesTab({ agent }: { agent: AgentDetail }) {
  const qc = useQueryClient();
  const agentId = agent.id;
  const categories = useTestCategories();
  const [category, setCategory] = useState<string>(ALL_CATEGORIES);
  const filtered = category === ALL_CATEGORIES ? null : category;
  const [page, setPage] = useState(1);
  const cases = useTestCases(agentId, filtered, page);
  const runs = useTestRuns(agentId);
  const [runId, setRunId] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const [editing, setEditing] = useState<Editing>(null);
  const [dialog, setDialog] = useState<"generate" | "import" | null>(null);
  const [removing, setRemoving] = useState<TestCase | null>(null);
  const [removePending, setRemovePending] = useState(false);
  const [target, setTarget] = useState<TestTarget["type"]>("draft");
  const [runError, setRunError] = useState<unknown>(null);
  const [starting, setStarting] = useState(false);
  const runKey = useActionKey();
  const blocked = useNotRunnable(agent);
  const editPath = `/agents/${agentId}/${agent.type === "flow" ? "flow" : "edit"}`;

  const latestId = runs.data?.items[0]?.test_run_id ?? null;
  useEffect(() => {
    if (!runId && latestId) setRunId(latestId);
  }, [runId, latestId]);

  const rows = cases.data?.items;
  const total = cases.data?.total ?? 0;
  const pageIds = (rows ?? []).map((r) => r.test_case_id);
  const pageAll = pageIds.length > 0 && pageIds.every((id) => selected.has(id));
  const pageSome = pageIds.some((id) => selected.has(id));
  const declared = useMemo(() => agent.draft_config.dynamic_variables ?? [], [agent.draft_config]);

  const toggle = (id: string) => {
    runKey.reset();
    setSelected((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };
  const togglePage = () => {
    runKey.reset();
    setSelected((s) => {
      const next = new Set(s);
      for (const id of pageIds) {
        if (pageAll) next.delete(id);
        else next.add(id);
      }
      return next;
    });
  };

  const runLabel = selected.size
    ? `Run ${plural(selected.size, "case")}`
    : filtered
      ? `Run ${categories.data?.find((c) => c.slug === filtered)?.name ?? "category"}`
      : "Run all";

  const run = async () => {
    setStarting(true);
    setRunError(null);
    try {
      const started = await startTestRun(
        {
          agent_id: agentId,
          target: { type: target },
          ...(selected.size ? { test_case_ids: [...selected] } : filtered ? { category: filtered } : {}),
        },
        runKey.current(),
      );
      runKey.reset();
      setSelected(new Set());
      setRunId(started.test_run_id);
      await qc.invalidateQueries({ queryKey: testingKeys.runs(agentId) });
      toast({
        tone: "info",
        title: `Run ${started.number ?? ""} started`.replace("  ", " "),
        description: `${plural(started.total, "test case")} queued.`,
      });
    } catch (e) {
      if (!isRetryable(e)) runKey.reset();
      setRunError(e);
    } finally {
      setStarting(false);
    }
  };

  const remove = async () => {
    if (!removing) return;
    setRemovePending(true);
    try {
      await deleteTestCase(removing.test_case_id);
      setSelected((s) => {
        const next = new Set(s);
        next.delete(removing.test_case_id);
        return next;
      });
      await qc.invalidateQueries({ queryKey: testingKeys.cases(agentId) });
      toast({ tone: "success", title: "Test case deleted", description: "Past runs keep their copy of it." });
      setRemoving(null);
    } catch (e) {
      toast({ tone: "error", title: "Not deleted", description: problemText(e, "test case") });
    } finally {
      setRemovePending(false);
    }
  };

  const doExport = async (template: boolean) => {
    try {
      const file = await exportTestCases(agentId, template);
      downloadJson(
        template ? "callwright_test_cases_template.json" : `${agent.name.replace(/[^a-z0-9]+/gi, "_").toLowerCase()}_test_cases.json`,
        file,
      );
    } catch (e) {
      toast({ tone: "error", title: "Export failed", description: problemText(e) });
    }
  };

  return (
    <div className="flex flex-col gap-6">
      {blocked && (
        <FormAlert
          tone="warning"
          action={
            <Button asChild size="sm" variant="secondary" className="w-fit">
              <Link to={editPath}>Open the agent editor</Link>
            </Button>
          }
        >
          {blocked}
        </FormAlert>
      )}

      <section aria-label="Test cases" className="overflow-hidden rounded-panel border border-line bg-surface shadow-1">
        <div className="flex flex-col gap-3 border-b border-line px-4 py-3 sm:px-5 lg:flex-row lg:items-center">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <Select
              size="sm"
              aria-label="Category"
              className="w-[200px]"
              value={category}
              onValueChange={(v) => {
                setCategory(v);
                setPage(1);
                runKey.reset();
              }}
              options={[{ value: ALL_CATEGORIES, label: "All categories" }, ...categoryOptions(categories.data)]}
            />
            <span className="text-[12.5px] text-fg-3" aria-live="polite">
              {cases.data ? plural(total, "case") : <Skeleton className="h-3 w-14" />}
            </span>
          </div>
          <div className="flex flex-wrap items-center gap-2 lg:ml-auto">
            <Button size="sm" variant="ghost" icon={<Plus aria-hidden />} onClick={() => setEditing({ mode: "new" })}>
              New case
            </Button>
            <Button size="sm" variant="ghost" icon={<Sparkles aria-hidden />} onClick={() => setDialog("generate")} disabled={Boolean(blocked)}>
              Generate
            </Button>
            <Menu>
              <MenuTrigger asChild>
                <Button size="sm" variant="ghost" icon={<FileDown aria-hidden />}>
                  Import and export
                </Button>
              </MenuTrigger>
              <MenuContent>
                <MenuItem onSelect={() => setDialog("import")}>
                  <Upload aria-hidden /> Import from JSON
                </MenuItem>
                <MenuItem onSelect={() => void doExport(false)}>
                  <Download aria-hidden /> Export test cases
                </MenuItem>
                <MenuItem onSelect={() => void doExport(true)}>
                  <FileDown aria-hidden /> Download empty template
                </MenuItem>
              </MenuContent>
            </Menu>
            <Select
              size="sm"
              aria-label="Run against"
              className="w-[160px]"
              value={target}
              onValueChange={(v) => {
                setTarget(v as TestTarget["type"]);
                runKey.reset();
              }}
              options={[
                { value: "draft", label: "Saved draft" },
                { value: "published", label: "Published version", disabled: !agent.published_version },
              ]}
            />
            <Button
              size="sm"
              variant="primary"
              icon={<Play aria-hidden />}
              pending={starting}
              disabled={Boolean(blocked) || total === 0}
              onClick={() => void run()}
            >
              {runLabel}
            </Button>
          </div>
        </div>
        {runError ? <ProblemAlert error={runError} kind="test run" className="px-5 pt-4 [&>div]:mb-4" /> : null}

        {cases.isError && !cases.data ? (
          <EmptyState
            compact
            icon={<ClipboardText weight="duotone" />}
            title="Test cases did not load"
            actions={<Button onClick={() => void cases.refetch()}>Try again</Button>}
          >
            {problemText(cases.error, "test case")}
          </EmptyState>
        ) : rows && rows.length === 0 ? (
          <EmptyState
            compact
            icon={<ClipboardText weight="duotone" />}
            title={filtered ? "No test cases in this category" : "No test cases yet"}
            actions={
              <>
                <Button variant="primary" icon={<Plus aria-hidden />} onClick={() => setEditing({ mode: "new" })}>
                  New case
                </Button>
                <Button icon={<Sparkles aria-hidden />} onClick={() => setDialog("generate")} disabled={Boolean(blocked)}>
                  Generate drafts
                </Button>
              </>
            }
          >
            A test case is one thing a caller says and how the agent should respond. Start with the five built-in categories: out of scope, bad
            behaviour, identity, prompt injection and guardrails.
          </EmptyState>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-[13px]">
              <caption className="sr-only">Test cases</caption>
              <thead>
                <tr className="border-b border-line bg-surface-2/70">
                  <th scope="col" className="h-9 w-12 pl-5 pr-2 text-left">
                    <Checkbox
                      checked={pageAll}
                      mixed={!pageAll && pageSome}
                      onChange={togglePage}
                      label={pageAll ? "Clear this page" : "Select this page"}
                    />
                  </th>
                  <th scope="col" className="h-9 px-3 text-left text-[12px] font-medium text-fg-3">
                    Case
                  </th>
                  <th scope="col" className="hidden h-9 px-3 text-left text-[12px] font-medium text-fg-3 md:table-cell">
                    Category
                  </th>
                  <th scope="col" className="h-9 px-3 text-left text-[12px] font-medium text-fg-3">
                    Last run
                  </th>
                  <th scope="col" className="h-9 w-12 pr-4">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody className={cases.isPlaceholderData ? "opacity-60 transition-opacity" : "transition-opacity"}>
                {!rows
                  ? Array.from({ length: 5 }, (_, i) => (
                      <tr key={i} className="border-b border-line last:border-0">
                        <td className="h-14 pl-5">
                          <Skeleton className="size-[18px] rounded-[5px]" />
                        </td>
                        <td className="px-3">
                          <Skeleton className="h-3 w-2/3" />
                        </td>
                        <td className="hidden px-3 md:table-cell">
                          <Skeleton className="h-3 w-20" />
                        </td>
                        <td className="px-3">
                          <Skeleton className="h-3 w-12" />
                        </td>
                        <td />
                      </tr>
                    ))
                  : rows.map((tc) => (
                      <tr
                        key={tc.test_case_id}
                        className={
                          selected.has(tc.test_case_id)
                            ? "border-b border-line bg-accent-soft/50 last:border-0"
                            : "border-b border-line last:border-0 hover:bg-accent-soft/25"
                        }
                      >
                        <td className="h-14 w-12 pl-5 pr-2 align-middle">
                          <Checkbox checked={selected.has(tc.test_case_id)} onChange={() => toggle(tc.test_case_id)} label={`Select ${tc.name}`} />
                        </td>
                        <td className="max-w-0 px-3 py-2.5 align-middle">
                          <button
                            type="button"
                            onClick={() => setEditing({ mode: "edit", tc })}
                            className="flex w-full min-w-0 cursor-pointer flex-col gap-0.5 rounded-inline text-left"
                          >
                            <span className="truncate text-[13.5px] font-medium text-fg">{tc.name}</span>
                            <span className="truncate text-[12.5px] text-fg-3">{tc.user_prompt}</span>
                          </button>
                        </td>
                        <td className="hidden w-[180px] px-3 align-middle md:table-cell">
                          <CategoryLabel slug={tc.category} categories={categories.data} />
                        </td>
                        <td className="w-[110px] px-3 align-middle">
                          <TestStatusBadge status={tc.last_status} />
                        </td>
                        <td className="w-12 pr-4 text-right align-middle">
                          <Menu>
                            <MenuTrigger asChild>
                              <IconButton label={`Actions for ${tc.name}`}>
                                <MoreHorizontal className="size-4" aria-hidden />
                              </IconButton>
                            </MenuTrigger>
                            <MenuContent>
                              <MenuItem onSelect={() => setEditing({ mode: "edit", tc })}>
                                <Pencil aria-hidden /> Edit
                              </MenuItem>
                              <MenuItem danger onSelect={() => setRemoving(tc)}>
                                <Trash2 aria-hidden /> Delete
                              </MenuItem>
                            </MenuContent>
                          </Menu>
                        </td>
                      </tr>
                    ))}
              </tbody>
            </table>
          </div>
        )}
        {cases.data && total > CASES_PAGE_SIZE && (
          <div className="border-t border-line">
            <Pagination
              page={page}
              totalPages={cases.data.total_pages}
              total={total}
              pageSize={CASES_PAGE_SIZE}
              noun="cases"
              onPageChange={setPage}
            />
          </div>
        )}
      </section>

      <TestRunPanel agentId={agentId} runs={runs.data?.items} runId={runId} onRunId={setRunId} categories={categories.data} />

      {editing && categories.data && (
        <TestCaseEditor
          key={editing.mode === "edit" ? editing.tc.test_case_id : "new"}
          open
          onOpenChange={(o) => !o && setEditing(null)}
          agentId={agentId}
          testCase={editing.mode === "edit" ? editing.tc : null}
          categories={categories.data}
          filteredCategory={filtered}
          declared={declared}
          onSaved={() => void qc.invalidateQueries({ queryKey: testingKeys.cases(agentId) })}
        />
      )}
      {dialog === "generate" && categories.data && (
        <GenerateDialog open onOpenChange={(o) => !o && setDialog(null)} agentId={agentId} categories={categories.data} />
      )}
      {dialog === "import" && <ImportDialog open onOpenChange={(o) => !o && setDialog(null)} agentId={agentId} />}
      <ConfirmDialog
        open={Boolean(removing)}
        onOpenChange={(o) => !o && setRemoving(null)}
        tone="danger"
        title="Delete this test case?"
        description={removing ? `"${removing.name}" is removed from the list. Past runs keep their copy, so their results stay readable.` : undefined}
        confirmLabel="Delete"
        pending={removePending}
        onConfirm={() => void remove()}
      />
    </div>
  );
}
