/**
 * "Add to dataset" (US5, T084): pick a dataset of the call's agent, or create one inline, and add
 * the call (or the selected calls). The result says what was added and what was skipped and why.
 * Mounted in the call detail drawer and the Call History selection bar.
 */
import { useQueryClient } from "@tanstack/react-query";
import { Database, Loader2, Plus } from "lucide-react";
import { useState } from "react";
import { addDatasetItems, datasetKeys, describeAddResult, useAgentDatasets, type Dataset } from "../../api/datasets";
import { Button, MenuContent, MenuItem, MenuLabel, MenuSeparator, Menu, MenuTrigger, toast } from "../../components";
import { problemText } from "../simulations/shared";
import { NewDatasetDialog } from "./NewDatasetDialog";

export function AddToDatasetMenu({
  agentId,
  callIds,
  size = "sm",
  label = "Add to dataset",
  compact = false,
}: {
  agentId: string;
  callIds: string[];
  size?: "sm" | "md";
  label?: string;
  /** Icon only below the sm breakpoint. */
  compact?: boolean;
}) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const datasets = useAgentDatasets(agentId, open);

  const add = async (d: Dataset) => {
    try {
      const res = await addDatasetItems(d.dataset_id, callIds);
      void qc.invalidateQueries({ queryKey: datasetKeys.all });
      toast({
        tone: res.added ? "success" : "info",
        title: res.added ? `Added to ${d.name}` : `Nothing added to ${d.name}`,
        description: describeAddResult(res),
      });
    } catch (e) {
      toast({ tone: "error", title: `Not added to ${d.name}`, description: problemText(e, "dataset") });
    }
  };

  return (
    <>
      <Menu open={open} onOpenChange={setOpen}>
        <MenuTrigger asChild>
          <Button size={size} variant="secondary" icon={<Database aria-hidden />} aria-label={compact ? label : undefined}>
            {compact ? <span className="hidden sm:inline">{label}</span> : label}
          </Button>
        </MenuTrigger>
        <MenuContent className="max-h-[360px] overflow-y-auto">
          <MenuLabel>Datasets of this agent</MenuLabel>
          {datasets.isPending ? (
            <div className="flex h-9 items-center gap-2 px-2 text-[13px] text-fg-3">
              <Loader2 className="size-4 animate-spin" aria-hidden /> Loading
            </div>
          ) : datasets.isError ? (
            <p className="px-2 py-2 text-[13px] text-danger-text">{problemText(datasets.error, "dataset")}</p>
          ) : (datasets.data ?? []).length === 0 ? (
            <p className="px-2 py-2 text-[13px] text-fg-3">No datasets for this agent yet.</p>
          ) : (
            datasets.data!.map((d) => (
              <MenuItem key={d.dataset_id} onSelect={() => void add(d)}>
                <span className="min-w-0 flex-1 truncate">{d.name}</span>
                <span className="font-mono text-[12px] text-fg-3 tnum">{d.item_count}</span>
              </MenuItem>
            ))
          )}
          <MenuSeparator />
          <MenuItem onSelect={() => setCreating(true)}>
            <Plus aria-hidden /> New dataset
          </MenuItem>
        </MenuContent>
      </Menu>
      {creating && (
        <NewDatasetDialog
          open
          onOpenChange={setCreating}
          defaultAgentId={agentId}
          lockAgent
          callIds={callIds}
          onCreated={() => void qc.invalidateQueries({ queryKey: datasetKeys.all })}
        />
      )}
    </>
  );
}
