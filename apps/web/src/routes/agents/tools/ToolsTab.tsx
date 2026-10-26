import { Toolbox } from "@phosphor-icons/react";
import { FlaskConical, Link2, MessageCircleMore, Pencil, Plus, Unlink, Users, Wrench } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";
import {
  MAX_TOOLS_PER_AGENT,
  useToolsByIds,
  type EndCallConfig,
  type HttpToolConfig,
  type PressDigitConfig,
  type Tool,
  type TransferConfig,
} from "../../../api/tools";
import { problemMessage } from "../../../api/problems";
import { Badge, Button, EmptyState, IconButton, Panel, Skeleton, Tooltip, toast } from "../../../components";
import { TabHeader } from "./TabHeader";
import type { EditorPanelProps } from "../editor/panelSlots";
import { AttachToolsDialog } from "./AttachToolsDialog";
import { ToolEditorDialog } from "./ToolEditorDialog";
import { TOOL_META, ToolTile } from "./toolMeta";

/** One line on what the tool does, in its own terms. */
export function toolSummary(tool: Tool): string {
  if (tool.type === "http") {
    const c = tool.config as HttpToolConfig;
    const url = c.url.replace(/^https?:\/\//, "");
    return `${c.method} ${url}`;
  }
  if (tool.type === "transfer_call") {
    const c = tool.config as TransferConfig;
    const where = c.routing_type === "static" ? (c.number ?? "") : "Agent chooses the number";
    return `${c.transfer_type === "warm" ? "Warm" : "Cold"} transfer to ${where}`;
  }
  if (tool.type === "end_call")
    return (tool.config as EndCallConfig).message ? `Says "${(tool.config as EndCallConfig).message}"` : "Hangs up without a goodbye";
  const c = tool.config as PressDigitConfig;
  return `Waits ${(c.delay_ms / 1000).toFixed(1)} s, ${(c.cooldown_ms / 1000).toFixed(1)} s between presses`;
}

function ToolRow({ tool, onEdit, onDetach }: { tool: Tool; onEdit: () => void; onDetach: () => void }) {
  const http = tool.type === "http";
  const missingMock = http && !(tool.mock_response ?? "").trim();
  const waiting = http && (tool.config as HttpToolConfig).speak_during_execution;
  return (
    <motion.li
      layout
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, x: -12 }}
      transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
      className="group flex min-w-0 items-start gap-3.5 px-5 py-4 transition-colors duration-150 hover:bg-surface-2/50"
    >
      <ToolTile type={tool.type} />
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
          <button
            type="button"
            onClick={onEdit}
            className="min-w-0 truncate rounded-inline font-mono text-[13.5px] font-semibold text-fg hover:text-accent-text focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
          >
            {tool.name}
          </button>
          <span className="text-[12px] text-fg-3">{TOOL_META[tool.type].label}</span>
        </div>
        <p className="line-clamp-2 text-[13px] leading-relaxed text-fg-2">{tool.description}</p>
        <p className="w-fit max-w-full truncate rounded-inline bg-surface-2 px-1.5 py-0.5 font-mono text-[11.5px] text-fg-3">{toolSummary(tool)}</p>
        <div className="mt-1 flex flex-wrap items-center gap-1.5">
          {waiting && <Badge icon={<MessageCircleMore />}>Waiting line</Badge>}
          {missingMock && (
            <Tooltip content="Simulations answer with an error for this tool until it has a canned response.">
              <span tabIndex={0} className="rounded-full focus-visible:outline-2 focus-visible:outline-ring">
                <Badge tone="warning" icon={<FlaskConical />}>
                  No canned response
                </Badge>
              </span>
            </Tooltip>
          )}
          {tool.usage_count > 1 && <Badge icon={<Users />}>Used by {tool.usage_count} agents</Badge>}
        </div>
      </div>
      <div className="-mr-2 flex shrink-0 items-center opacity-100 transition-opacity sm:opacity-60 sm:group-focus-within:opacity-100 sm:group-hover:opacity-100">
        <IconButton label={`Edit ${tool.name}`} className="size-8" onClick={onEdit}>
          <Pencil className="size-4" aria-hidden />
        </IconButton>
        <IconButton label={`Detach ${tool.name}`} className="size-8 hover:bg-danger-soft hover:text-danger-text" onClick={onDetach}>
          <Unlink className="size-4" aria-hidden />
        </IconButton>
      </div>
    </motion.li>
  );
}

/**
 * The agent's Tools tab (T030, T088): tools attached to the draft, from the workspace library.
 * Attaching, detaching and creating change the draft (saved with the agent); editing a tool
 * changes the library entry for every agent that uses it.
 */
export function ToolsTab({ config, update }: EditorPanelProps) {
  const ids = (config.tool_ids ?? []) as string[];
  const tools = useToolsByIds(ids);
  const [attachOpen, setAttachOpen] = useState(false);
  const [editor, setEditor] = useState<{ tool: Tool | null; key: number } | null>(null);
  const attached = tools.data ?? [];
  const full = ids.length >= MAX_TOOLS_PER_AGENT;
  const allowHttp = import.meta.env.DEV;

  const attach = (picked: Tool[]) => {
    const names = new Set(attached.map((t) => t.name));
    const add = picked.filter((t) => !ids.includes(t.id) && !names.has(t.name)).slice(0, MAX_TOOLS_PER_AGENT - ids.length);
    if (add.length === 0) return;
    update((d) => {
      d.tool_ids = [...((d.tool_ids ?? []) as string[]), ...add.map((t) => t.id)];
    });
  };
  const detach = (tool: Tool) => {
    update((d) => {
      d.tool_ids = ((d.tool_ids ?? []) as string[]).filter((id) => id !== tool.id);
    });
    toast({ title: `${tool.name} detached`, description: "Save the agent to keep the change. The tool stays in your library." });
  };
  const openEditor = (tool: Tool | null) => setEditor({ tool, key: Date.now() });

  return (
    <div className="flex flex-col gap-4">
      <Panel bodyClassName="p-0">
        <TabHeader
          title="Tools"
          icon={<Wrench aria-hidden />}
          description={`Actions the agent can take during a call. ${ids.length} of ${MAX_TOOLS_PER_AGENT} attached.`}
          actions={
            ids.length > 0 ? (
              <>
                <Button size="sm" icon={<Link2 aria-hidden />} disabled={full} onClick={() => setAttachOpen(true)}>
                  Attach
                </Button>
                <Button size="sm" variant="primary" icon={<Plus aria-hidden />} disabled={full} onClick={() => openEditor(null)}>
                  New tool
                </Button>
              </>
            ) : undefined
          }
        />
        {tools.isPending && ids.length > 0 ? (
          <div className="flex flex-col gap-3 p-5" aria-busy="true" aria-label="Loading tools">
            {ids.slice(0, 3).map((id) => (
              <Skeleton key={id} className="h-[78px] w-full rounded-panel" />
            ))}
          </div>
        ) : tools.isError ? (
          <EmptyState compact icon={<Toolbox weight="duotone" />} title="Tools did not load">
            {problemMessage(tools.error, "tool")}
          </EmptyState>
        ) : attached.length === 0 ? (
          <div className="relative overflow-hidden">
            <div aria-hidden className="glow-backdrop pointer-events-none absolute inset-0 opacity-50" />
            <EmptyState
              compact
              className="relative"
              icon={<Toolbox weight="duotone" />}
              title="No tools yet"
              actions={
                <>
                  <Button variant="primary" icon={<Plus aria-hidden />} onClick={() => openEditor(null)}>
                    New tool
                  </Button>
                  <Button icon={<Link2 aria-hidden />} onClick={() => setAttachOpen(true)}>
                    Attach from library
                  </Button>
                </>
              }
            >
              Let the agent end the call, transfer to a person, press keypad digits or call your own API with details from the conversation.
            </EmptyState>
          </div>
        ) : (
          <ul className="divide-y divide-line" aria-label="Attached tools">
            <AnimatePresence initial={false}>
              {attached.map((t) => (
                <ToolRow key={t.id} tool={t} onEdit={() => openEditor(t)} onDetach={() => detach(t)} />
              ))}
            </AnimatePresence>
          </ul>
        )}
      </Panel>

      <AttachToolsDialog
        open={attachOpen}
        onOpenChange={setAttachOpen}
        attached={attached}
        onAttach={attach}
        onCreate={() => {
          setAttachOpen(false);
          openEditor(null);
        }}
      />
      {editor && (
        <ToolEditorDialog
          key={editor.key}
          open
          onOpenChange={(o) => !o && setEditor(null)}
          tool={editor.tool}
          allowHttp={allowHttp}
          onSaved={(saved, created) => {
            if (created) attach([saved]);
          }}
        />
      )}
    </div>
  );
}
