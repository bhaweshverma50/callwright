/**
 * Dataset page `/datasets/:datasetId` (US5, T083, T095): the dataset's calls page by page with the
 * total, "unavailable" markers for calls whose transcript was removed by retention (bulk actions
 * skip them), remove a call, re-run every check on all calls, edit, delete, and start a batch
 * simulation over the whole dataset.
 */
import { Database as DatabaseDuo } from "@phosphor-icons/react";
import { useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, FlaskConical, MoreHorizontal, Pencil, ShieldCheck, Trash2, X } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import {
  ITEMS_PAGE_SIZE,
  datasetKeys,
  deleteDataset,
  evaluateDataset,
  removeDatasetItem,
  updateDataset,
  useDataset,
  useDatasetItems,
  type Dataset,
  type DatasetItem,
} from "../../api/datasets";
import { isApiError } from "../../api/errors";
import { isRetryable, useActionKey } from "../../api/paid";
import { fieldErrors, problemText } from "../../api/problems";
import {
  Badge,
  Button,
  CallStatusBadge,
  cn,
  type Column,
  ConfirmDialog,
  Dialog,
  EmptyState,
  Field,
  IconButton,
  Input,
  Menu,
  MenuContent,
  MenuItem,
  MenuTrigger,
  PageHeader,
  Pagination,
  PanelLoader,
  ProblemAlert,
  SentimentBadge,
  Switch,
  Table,
  Textarea,
  toast,
  Tooltip,
} from "../../components";
import { RecordNotFound } from "../NotFound";
import { StartSimulationDialog } from "../simulations/StartSimulationDialog";
import { mss, plural, shortId, timeAgo, when } from "../../lib/format";
import { bodyLimits } from "../../lib/contract.gen";
import { CALLS_PATH, DATASETS_PATH, callPath } from "../../lib/paths";

// The call's evaluation status from 007: its current checks passed, one failed, still running,
// none ran, or a check errored.
const EVAL_LABELS: Record<string, string> = {
  passed: "Checks passed",
  failed: "A check failed",
  running: "Checking",
  not_evaluated: "Not checked",
  error: "Check error",
};

function columns(onRemove: (item: DatasetItem) => void): Column<DatasetItem>[] {
  const dim = (i: DatasetItem) => (i.available ? "" : "text-fg-3");
  return [
    {
      key: "call",
      header: "Call",
      cell: (i) => (
        <span className="flex min-w-0 items-center gap-2">
          <Link
            to={callPath(i.call_id)}
            title={i.call_id}
            className={cn("block whitespace-nowrap rounded-inline font-mono text-[13px] hover:underline", i.available ? "text-fg" : "text-fg-3")}
          >
            {shortId(i.call_id)}
          </Link>
          {!i.available && (
            <Tooltip content="The transcript was removed by retention. Bulk actions skip this call.">
              <span tabIndex={0}>
                <Badge tone="warning">Unavailable</Badge>
              </span>
            </Tooltip>
          )}
        </span>
      ),
    },
    {
      key: "started",
      header: "Call time",
      cell: (i) => <span className={cn("whitespace-nowrap text-fg-2", dim(i))}>{i.started_at ? when(i.started_at) : "n/a"}</span>,
    },
    { key: "duration", header: "Duration", numeric: true, hideOnNarrow: true, cell: (i) => (i.duration_s != null ? mss(i.duration_s) : "n/a") },
    {
      key: "status",
      header: "Status",
      hideOnNarrow: true,
      cell: (i) => (i.call_status ? <CallStatusBadge status={i.call_status} /> : <span className="text-fg-3">n/a</span>),
    },
    {
      key: "eval",
      header: "Checks",
      hideOnNarrow: true,
      cell: (i) => <span className={cn("whitespace-nowrap text-fg-2", dim(i))}>{i.eval_status ? EVAL_LABELS[i.eval_status] : "n/a"}</span>,
    },
    {
      key: "sentiment",
      header: "Sentiment",
      hideOnNarrow: true,
      cell: (i) => <SentimentBadge value={i.sentiment} />,
    },
    { key: "added", header: "Added", hideOnNarrow: true, cell: (i) => <span className="whitespace-nowrap text-fg-2">{timeAgo(i.added_at)}</span> },
    {
      key: "remove",
      header: <span className="sr-only">Remove</span>,
      align: "right",
      cell: (i) => (
        <IconButton label={`Remove ${i.call_id} from the dataset`} onClick={() => onRemove(i)}>
          <X className="size-4" aria-hidden />
        </IconButton>
      ),
    },
  ];
}

function EditDialog({ dataset, onClose }: { dataset: Dataset; onClose: () => void }) {
  const qc = useQueryClient();
  const [name, setName] = useState(dataset.name);
  const [description, setDescription] = useState(dataset.description ?? "");
  const [nameError, setNameError] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [pending, setPending] = useState(false);
  const save = async () => {
    if (!name.trim()) {
      setNameError("Enter a name");
      return;
    }
    setPending(true);
    setError(null);
    try {
      const d = await updateDataset(dataset.dataset_id, { name: name.trim(), description: description.trim() || null });
      qc.setQueryData(datasetKeys.detail(d.dataset_id), d);
      void qc.invalidateQueries({ queryKey: datasetKeys.all });
      onClose();
    } catch (e) {
      const fe = fieldErrors(e).name ?? (isApiError(e) && e.status === 409 ? (e.problem.detail ?? "That name is already in use.") : null);
      setNameError(fe);
      if (!fe) setError(e);
    } finally {
      setPending(false);
    }
  };
  return (
    <Dialog
      open
      onOpenChange={(o) => !o && onClose()}
      title="Edit dataset"
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" pending={pending} onClick={() => void save()}>
            Save
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <Field label="Name" error={nameError}>
          {({ id, describedBy, invalid }) => (
            <Input
              id={id}
              aria-describedby={describedBy}
              aria-invalid={invalid}
              maxLength={bodyLimits["PATCH /datasets/{dataset_id}"].name.maxLength}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          )}
        </Field>
        <Field label="Description" hint="Optional.">
          {({ id, describedBy }) => (
            <Textarea
              id={id}
              aria-describedby={describedBy}
              rows={2}
              maxLength={bodyLimits["PATCH /datasets/{dataset_id}"].description.maxLength}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          )}
        </Field>
        <ProblemAlert error={error} kind="dataset" />
      </div>
    </Dialog>
  );
}

function EvaluateDialog({ dataset, onClose }: { dataset: Dataset; onClose: () => void }) {
  const key = useActionKey();
  const [onlyMissing, setOnlyMissing] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [pending, setPending] = useState(false);
  const run = async () => {
    setPending(true);
    setError(null);
    try {
      const res = await evaluateDataset(dataset.dataset_id, onlyMissing, key.current());
      key.reset();
      const skipped = [
        res.skipped_up_to_date ? `${res.skipped_up_to_date} already up to date` : "",
        res.skipped_unavailable ? `${res.skipped_unavailable} unavailable` : "",
      ].filter(Boolean);
      toast({
        tone: "success",
        title: `${plural(res.enqueued, "call")} queued for evaluation`,
        ...(skipped.length && { description: `Skipped: ${skipped.join(", ")}.` }),
      });
      onClose();
    } catch (e) {
      if (!isRetryable(e)) key.reset();
      setError(e);
    } finally {
      setPending(false);
    }
  };
  return (
    <Dialog
      open
      onOpenChange={(o) => !o && onClose()}
      icon={<ShieldCheck aria-hidden />}
      title="Run checks on every call"
      description={`Every check enabled on ${dataset.agent_name ?? "the agent"} runs on the available calls of this dataset. Evaluations are charged per call like any other check.`}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" pending={pending} onClick={() => void run()}>
            Run checks
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <Switch
          checked={onlyMissing}
          onCheckedChange={(v) => {
            setOnlyMissing(v);
            key.reset();
          }}
          label="Only calls without current results"
          description="Skip calls already checked by the current version of every check."
        />
        <ProblemAlert error={error} kind="dataset" />
      </div>
    </Dialog>
  );
}

export function DatasetPage() {
  const { datasetId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const page = Math.max(1, Number(params.get("page") ?? 1) || 1);
  const dataset = useDataset(datasetId);
  const items = useDatasetItems(datasetId, page);
  const [dialog, setDialog] = useState<"simulate" | "evaluate" | "edit" | "delete" | null>(null);
  const [removing, setRemoving] = useState<DatasetItem | null>(null);
  const [pending, setPending] = useState(false);

  if (isApiError(dataset.error) && dataset.error.status === 404)
    return <RecordNotFound kind="dataset" backTo={DATASETS_PATH} backLabel="Back to Datasets" />;
  if (dataset.isError)
    return (
      <EmptyState
        icon={<DatabaseDuo weight="duotone" />}
        title="The dataset did not load"
        actions={<Button onClick={() => void dataset.refetch()}>Try again</Button>}
      >
        {problemText(dataset.error, "dataset")}
      </EmptyState>
    );
  if (!dataset.data) return <PanelLoader label="Opening dataset" />;
  const d = dataset.data;
  const total = items.data?.total ?? d.item_count;

  const remove = async () => {
    if (!removing) return;
    setPending(true);
    try {
      await removeDatasetItem(d.dataset_id, removing.call_id);
      await Promise.all([
        qc.invalidateQueries({ queryKey: datasetKeys.items(d.dataset_id, page) }),
        qc.invalidateQueries({ queryKey: datasetKeys.detail(d.dataset_id) }),
      ]);
      toast({ tone: "success", title: "Call removed", description: "The call itself is untouched." });
      setRemoving(null);
    } catch (e) {
      toast({ tone: "error", title: "Not removed", description: problemText(e) });
    } finally {
      setPending(false);
    }
  };

  const destroy = async () => {
    setPending(true);
    try {
      await deleteDataset(d.dataset_id);
      void qc.invalidateQueries({ queryKey: datasetKeys.all });
      toast({ tone: "success", title: `Deleted ${d.name}`, description: "The calls themselves are untouched." });
      navigate(DATASETS_PATH);
    } catch (e) {
      toast({ tone: "error", title: "Not deleted", description: problemText(e) });
    } finally {
      setPending(false);
    }
  };

  const tooFew = d.item_count < 2;
  return (
    <div className="flex flex-col">
      <Link
        to={DATASETS_PATH}
        className="link-underline mb-4 inline-flex w-fit items-center gap-1 rounded-inline text-[13px] text-fg-2 hover:text-fg"
      >
        <ChevronLeft className="size-4" aria-hidden /> Back to Datasets
      </Link>
      <PageHeader
        title={<span className="break-words">{d.name}</span>}
        description={
          <>
            {d.description ? `${d.description} ` : ""}
            <span className="text-fg-3">
              {plural(d.item_count, "call")} of {d.agent_name ?? "one agent"}, updated {timeAgo(d.updated_at)}.
            </span>
          </>
        }
        actions={
          <>
            <Button icon={<ShieldCheck aria-hidden />} disabled={d.item_count === 0} onClick={() => setDialog("evaluate")}>
              Run checks
            </Button>
            <Tooltip content="A batch needs at least 2 calls." enabled={tooFew}>
              <span tabIndex={tooFew ? 0 : -1}>
                <Button variant="primary" icon={<FlaskConical aria-hidden />} disabled={tooFew} onClick={() => setDialog("simulate")}>
                  Run simulation
                </Button>
              </span>
            </Tooltip>
            <Menu>
              <MenuTrigger asChild>
                <IconButton label="More actions">
                  <MoreHorizontal className="size-4" aria-hidden />
                </IconButton>
              </MenuTrigger>
              <MenuContent>
                <MenuItem onSelect={() => setDialog("edit")}>
                  <Pencil aria-hidden /> Edit name and description
                </MenuItem>
                <MenuItem danger onSelect={() => setDialog("delete")}>
                  <Trash2 aria-hidden /> Delete dataset
                </MenuItem>
              </MenuContent>
            </Menu>
          </>
        }
      />
      <section aria-label="Calls in this dataset" className="relative overflow-hidden rounded-panel border border-line bg-surface shadow-1">
        <Table
          caption="Calls in this dataset, most recently added first"
          columns={columns(setRemoving)}
          rows={items.data?.items}
          rowKey={(i) => i.call_id}
          loading={items.isPending}
          stale={items.isPlaceholderData}
          skeletonRows={8}
          empty={
            <EmptyState
              compact
              icon={<DatabaseDuo weight="duotone" />}
              title="No calls yet"
              actions={
                <Button asChild>
                  <Link to={CALLS_PATH}>Open Calls</Link>
                </Button>
              }
            >
              Add calls from Calls (select them, then Add to dataset) or from a call's detail view.
            </EmptyState>
          }
        />
        {items.data && total > 0 && (
          <div className="border-t border-line">
            <Pagination
              page={page}
              totalPages={items.data.total_pages}
              total={total}
              pageSize={ITEMS_PAGE_SIZE}
              noun={total === 1 ? "call" : "calls"}
              onPageChange={(p) => {
                const next = new URLSearchParams(params);
                if (p === 1) next.delete("page");
                else next.set("page", String(p));
                setParams(next, { replace: true });
              }}
            />
          </div>
        )}
      </section>

      {dialog === "simulate" && (
        <StartSimulationDialog
          open
          onOpenChange={(o) => !o && setDialog(null)}
          agentId={d.agent_id}
          agentName={d.agent_name}
          dataset={{ id: d.dataset_id, name: d.name }}
        />
      )}
      {dialog === "evaluate" && <EvaluateDialog dataset={d} onClose={() => setDialog(null)} />}
      {dialog === "edit" && <EditDialog dataset={d} onClose={() => setDialog(null)} />}
      <ConfirmDialog
        open={dialog === "delete"}
        onOpenChange={(o) => !o && setDialog(null)}
        tone="danger"
        title={`Delete ${d.name}?`}
        description="The dataset and its list of calls are removed. The calls themselves, and batches already run from it, are untouched."
        confirmLabel="Delete dataset"
        pending={pending}
        onConfirm={() => void destroy()}
      />
      <ConfirmDialog
        open={Boolean(removing)}
        onOpenChange={(o) => !o && setRemoving(null)}
        title="Remove this call from the dataset?"
        description="The call stays in Calls; only this dataset stops using it."
        confirmLabel="Remove"
        pending={pending}
        onConfirm={() => void remove()}
      />
    </div>
  );
}
