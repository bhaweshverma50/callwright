import { CircleAlert, Copy, Trash2, TriangleAlert, X } from "lucide-react";
import { memo } from "react";
import type { LlmCatalog, VoiceCatalog } from "../../../api/agents";
import type { ConditionConfig, ConfigByNode, FlowEdge, FlowGraph, FlowNode, ValidationIssue } from "../../../api/flows";
import { IconButton, Input } from "../../../components";
import { NODE_META } from "../canvas/nodeMeta";
import { renameCategory } from "../model";
import { ConditionForm } from "./node-forms/ConditionForm";
import { ConversationalForm } from "./node-forms/ConversationalForm";
import { EndForm } from "./node-forms/EndForm";
import { ExtractForm } from "./node-forms/ExtractForm";
import { SayForm } from "./node-forms/SayForm";
import { StartForm } from "./node-forms/StartForm";
import { TransferNodeForm } from "./node-forms/TransferNodeForm";
import { WebhookForm } from "./node-forms/WebhookForm";

/**
 * The selected node's settings (T028): header with its name, then the form for its type in its
 * own scroll area. Memoised and fed only steps and connections (never the viewport), with stable
 * callbacks, so panning and dragging on the canvas leave it, its scroll position and its state
 * alone.
 */
export const NodePanel = memo(function NodePanel({
  node,
  nodes,
  edges,
  setGraph,
  issues,
  onClose,
  onDelete,
  onDuplicate,
  onSelectEdge,
  onCreateTool,
  catalogs,
  allowHttp,
  locked,
}: {
  node: FlowNode;
  nodes: FlowNode[];
  edges: FlowEdge[];
  setGraph: (g: FlowGraph | ((g: FlowGraph) => FlowGraph)) => void;
  issues: ValidationIssue[];
  onClose: () => void;
  onDelete: (node: FlowNode) => void;
  onDuplicate: (node: FlowNode) => void;
  onSelectEdge: (id: string) => void;
  onCreateTool: () => void;
  catalogs: { llm: LlmCatalog; voice: VoiceCatalog } | null;
  allowHttp: boolean;
  locked: boolean;
}) {
  const meta = NODE_META[node.type];
  const own = issues.filter((i) => i.node_id === node.id);
  const update = (patch: Partial<FlowNode>) =>
    setGraph((g) => ({ ...g, nodes: g.nodes.map((n) => (n.id === node.id ? ({ ...n, ...patch } as FlowNode) : n)) }));
  const setConfig = <T extends keyof ConfigByNode>(config: ConfigByNode[T]) => update({ config } as Partial<FlowNode>);
  const outgoing = edges.filter((e) => e.source === node.id);
  const startNext = node.type === "start" ? nodes.find((n) => n.id === outgoing[0]?.target)?.label : null;
  const taken = nodes
    .filter((n) => n.id !== node.id && n.type === "extract_variable")
    .flatMap((n) => (n.config as ConfigByNode["extract_variable"]).fields.map((f) => f.name));

  return (
    <div className="flex h-full min-h-0 flex-col" data-ntype={node.type}>
      <header className="panel-head flex items-start gap-3 border-b border-line px-5 py-4">
        <span className="fnode-chip mt-0.5" aria-hidden>
          {meta.icon}
        </span>
        <div className="min-w-0 flex-1">
          <p className="fnode-type">{meta.title}</p>
          <Input
            inputSize="sm"
            aria-label="Step name"
            value={node.label}
            maxLength={80}
            disabled={locked}
            onChange={(e) => update({ label: e.target.value })}
            onBlur={(e) => !e.target.value.trim() && update({ label: meta.title })}
            className="mt-1 -ml-2 border-transparent bg-transparent px-2 text-[15px] font-semibold shadow-none hover:border-line focus:border-line-strong"
          />
        </div>
        <div className="flex shrink-0 items-center">
          {node.type !== "start" && (
            <>
              <IconButton label="Duplicate step" className="size-8" disabled={locked} onClick={() => onDuplicate(node)}>
                <Copy className="size-4" aria-hidden />
              </IconButton>
              <IconButton label="Delete step" className="size-8 hover:text-danger-text" disabled={locked} onClick={() => onDelete(node)}>
                <Trash2 className="size-4" aria-hidden />
              </IconButton>
            </>
          )}
          <IconButton label="Close settings" className="size-8" onClick={onClose}>
            <X className="size-4" aria-hidden />
          </IconButton>
        </div>
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain" data-panel-scroll>
        {own.length > 0 && (
          <ul className="flex flex-col gap-1.5 border-b border-line bg-surface-2/50 px-5 py-3">
            {own.map((i, k) => (
              <li key={k} className="flex items-start gap-2 text-[13px] leading-relaxed">
                {i.severity === "error" ? (
                  <CircleAlert className="mt-0.5 size-3.5 shrink-0 text-danger-text" aria-label="Error" />
                ) : (
                  <TriangleAlert className="mt-0.5 size-3.5 shrink-0 text-warning-text" aria-label="Warning" />
                )}
                <span className={i.severity === "error" ? "text-danger-text" : "text-fg-2"}>{i.message}</span>
              </li>
            ))}
          </ul>
        )}
        <fieldset disabled={locked} className="min-w-0 pb-4">
          {node.type === "start" && (
            <StartForm config={node.config as ConfigByNode["start"]} onChange={setConfig} issues={own} nextLabel={startNext} />
          )}
          {(node.type === "agent" || node.type === "task") && (
            <ConversationalForm
              config={node.config as ConfigByNode["task"]}
              onChange={setConfig}
              issues={own}
              isTask={node.type === "task"}
              catalogs={catalogs}
              onCreateTool={onCreateTool}
            />
          )}
          {node.type === "condition" && (
            <ConditionForm
              config={node.config as ConditionConfig}
              onChange={setConfig}
              issues={own}
              outgoing={outgoing}
              onSelectEdge={onSelectEdge}
              onRenameCategory={(from, to, next) =>
                setGraph((g) => ({
                  ...g,
                  nodes: g.nodes.map((n) => (n.id === node.id ? ({ ...n, config: next } as FlowNode) : n)),
                  edges: renameCategory(g, node.id, from, to),
                }))
              }
            />
          )}
          {node.type === "say" && <SayForm config={node.config as ConfigByNode["say"]} onChange={setConfig} issues={own} />}
          {node.type === "extract_variable" && (
            <ExtractForm config={node.config as ConfigByNode["extract_variable"]} onChange={setConfig} issues={own} takenNames={taken} />
          )}
          {node.type === "webhook" && (
            <WebhookForm config={node.config as ConfigByNode["webhook"]} onChange={setConfig} issues={own} allowHttp={allowHttp} />
          )}
          {node.type === "transfer" && <TransferNodeForm config={node.config as ConfigByNode["transfer"]} onChange={setConfig} issues={own} />}
          {node.type === "end" && <EndForm config={node.config as ConfigByNode["end"]} onChange={setConfig} issues={own} />}
        </fieldset>
      </div>
    </div>
  );
});

export type { FlowEdge };
