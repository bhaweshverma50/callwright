import { MagnifyingGlass, Toolbox } from "@phosphor-icons/react";
import { Check, Link2, Plus, Search, X } from "lucide-react";
import { useMemo, useState } from "react";
import { MAX_TOOLS_PER_AGENT, useTools, type Tool } from "../../../api/tools";
import { problemMessage } from "../../../api/problems";
import { Badge, Button, Dialog, EmptyState, IconButton, Input, Skeleton, cn } from "../../../components";
import { useDebounced } from "../../../lib/useDebounced";
import { TOOL_META, ToolTile } from "./toolMeta";

/**
 * Pick tools from the workspace library (T030). Tools already attached are marked; a tool whose
 * name is already taken by another attached tool cannot be picked (names must be unique per
 * agent), and the selection stops at 25 tools.
 */
export function AttachToolsDialog({
  open,
  onOpenChange,
  attached,
  onAttach,
  onCreate,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  attached: Tool[];
  onAttach: (tools: Tool[]) => void;
  onCreate: () => void;
}) {
  const [search, setSearch] = useState("");
  const q = useDebounced(search.trim(), 200);
  const tools = useTools(q, null, 1, 100);
  const [picked, setPicked] = useState<Map<string, Tool>>(new Map());
  const attachedIds = useMemo(() => new Set(attached.map((t) => t.id)), [attached]);
  const takenNames = useMemo(() => new Set([...attached.map((t) => t.name), ...[...picked.values()].map((t) => t.name)]), [attached, picked]);
  const room = MAX_TOOLS_PER_AGENT - attached.length - picked.size;
  const items = tools.data?.items ?? [];

  const toggle = (t: Tool) =>
    setPicked((prev) => {
      const next = new Map(prev);
      if (next.has(t.id)) next.delete(t.id);
      else next.set(t.id, t);
      return next;
    });

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) setPicked(new Map());
        onOpenChange(o);
      }}
      size="lg"
      icon={<Link2 />}
      title="Attach tools"
      description={`Pick tools from your workspace library. ${attached.length} of ${MAX_TOOLS_PER_AGENT} attached.`}
      footer={
        <>
          <Button variant="ghost" icon={<Plus aria-hidden />} className="mr-auto" onClick={onCreate}>
            New tool
          </Button>
          <Button onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button
            variant="primary"
            icon={<Check aria-hidden />}
            disabled={picked.size === 0}
            onClick={() => {
              onAttach([...picked.values()]);
              setPicked(new Map());
              onOpenChange(false);
            }}
          >
            {picked.size === 0 ? "Attach" : `Attach ${picked.size} ${picked.size === 1 ? "tool" : "tools"}`}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <Input
          prefix={<Search aria-hidden />}
          placeholder="Search tools by name or description"
          aria-label="Search tools"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          suffix={
            search ? (
              <IconButton label="Clear search" className="size-6 [&_svg]:size-3.5" onClick={() => setSearch("")}>
                <X aria-hidden />
              </IconButton>
            ) : undefined
          }
        />
        <div className="max-h-[min(52vh,440px)] overflow-y-auto pr-1">
          {tools.isPending ? (
            <div className="flex flex-col gap-2" aria-busy="true" aria-label="Loading tools">
              {Array.from({ length: 4 }, (_, i) => (
                <Skeleton key={i} className="h-[66px] w-full rounded-panel" />
              ))}
            </div>
          ) : tools.isError ? (
            <EmptyState compact icon={<Toolbox weight="duotone" />} title="Tools did not load">
              {problemMessage(tools.error, "tool")}
            </EmptyState>
          ) : items.length === 0 ? (
            <EmptyState
              compact
              icon={q ? <MagnifyingGlass weight="duotone" /> : <Toolbox weight="duotone" />}
              title={q ? `No tools match "${q}"` : "Your tool library is empty"}
              actions={
                <Button icon={<Plus aria-hidden />} onClick={onCreate}>
                  New tool
                </Button>
              }
            >
              {q ? "Try part of the name or a word from the description." : "Create a tool once and use it in any agent."}
            </EmptyState>
          ) : (
            <ul className="flex flex-col gap-2" aria-label="Workspace tools">
              {items.map((t) => {
                const isAttached = attachedIds.has(t.id);
                const on = picked.has(t.id);
                const clash = !on && !isAttached && takenNames.has(t.name);
                const full = !on && !isAttached && room <= 0;
                const disabled = isAttached || clash || full;
                return (
                  <li key={t.id}>
                    <button
                      type="button"
                      role="checkbox"
                      aria-checked={on || isAttached}
                      aria-disabled={disabled || undefined}
                      disabled={disabled}
                      onClick={() => toggle(t)}
                      className={cn(
                        "flex w-full min-w-0 items-center gap-3 rounded-panel border px-3.5 py-3 text-left transition-[background-color,border-color,box-shadow] duration-150",
                        on
                          ? "border-accent bg-accent-soft/45 shadow-[0_0_0_1px_var(--accent)]"
                          : "border-line bg-surface hover:border-accent/45 hover:bg-surface-2/60",
                        disabled && "cursor-not-allowed opacity-60 hover:border-line hover:bg-surface",
                        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
                      )}
                    >
                      <ToolTile type={t.type} size="sm" />
                      <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                        <span className="flex min-w-0 items-center gap-2">
                          <span className="truncate font-mono text-[13px] font-medium text-fg">{t.name}</span>
                          <span className="shrink-0 text-[12px] text-fg-3">{TOOL_META[t.type].label}</span>
                        </span>
                        <span className="truncate text-[12.5px] text-fg-2">{t.description}</span>
                      </span>
                      {isAttached ? (
                        <Badge tone="success">Attached</Badge>
                      ) : clash ? (
                        <Badge tone="warning">Name in use</Badge>
                      ) : full ? (
                        <Badge>Limit reached</Badge>
                      ) : (
                        <span
                          aria-hidden
                          className={cn(
                            "grid size-5 shrink-0 place-items-center rounded-full border transition-[background-color,border-color,transform] duration-200",
                            on ? "scale-100 border-transparent grad-action text-white" : "scale-90 border-line-strong bg-surface text-transparent",
                          )}
                        >
                          <Check strokeWidth={3} className="size-3" />
                        </span>
                      )}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </div>
    </Dialog>
  );
}
