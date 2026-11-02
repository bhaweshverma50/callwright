/**
 * Target picker and variant editor (US2, T056, T057). A simulation runs against the published
 * version, the saved draft, an earlier version, or a variant: a copy of the saved draft with
 * unsaved edits to the prompt, flow node instructions and tool descriptions. The variant is sent
 * as a full configuration; nothing is saved to the agent.
 */
import { GitFork } from "lucide-react";
import { useMemo } from "react";
import { useAgent, useAgentVersions, type AgentConfig, type AgentDetail } from "../../api/agents";
import { useFlowByAgent, type FlowGraph } from "../../api/flows";
import type { SimTarget, TargetType } from "../../api/simulations";
import { useToolsByIds } from "../../api/tools";
import { Badge, Field, Input, Select, Skeleton, Textarea } from "../../components";

export interface Variant {
  label: string;
  /** Edited prompt (single-prompt agents). */
  prompt: string;
  /** Node id to edited instructions (flow agents). */
  nodes: Record<string, string>;
  /** Tool id to edited description. */
  tools: Record<string, string>;
}

export interface TargetChoice {
  type: TargetType;
  versionId: string | null;
  variant: Variant | null;
}

export const defaultTarget = (): TargetChoice => ({ type: "published", versionId: null, variant: null });

export function emptyVariant(config: AgentConfig | undefined): Variant {
  return { label: "", prompt: config?.prompt ?? "", nodes: {}, tools: {} };
}

/** The variant as a full configuration: the saved draft with the edits applied. */
export function variantConfig(
  base: AgentConfig,
  v: Variant,
  graph: FlowGraph | undefined,
  tools: { id: string; description: string }[],
): AgentConfig {
  const config = structuredClone(base) as unknown as Record<string, unknown> & AgentConfig;
  if (base.type === "single_prompt") config.prompt = v.prompt;
  if (graph && Object.keys(v.nodes).length) {
    const edited: FlowGraph = {
      ...graph,
      nodes: graph.nodes.map((n) =>
        v.nodes[n.id] !== undefined && "instructions" in n.config ? { ...n, config: { ...n.config, instructions: v.nodes[n.id]! } } : n,
      ) as FlowGraph["nodes"],
    };
    (config as Record<string, unknown>).flow = { ...((base.flow as Record<string, unknown> | null | undefined) ?? {}), graph: edited };
  }
  if (Object.keys(v.tools).length)
    (config as Record<string, unknown>).tools = tools.map((t) => ({ ...t, description: v.tools[t.id] ?? t.description }));
  return config as AgentConfig;
}

/** How many parts of the variant differ from the saved draft. */
export function variantChanges(base: AgentConfig | undefined, v: Variant | null): number {
  if (!v || !base) return 0;
  return (base.type === "single_prompt" && v.prompt !== base.prompt ? 1 : 0) + Object.keys(v.nodes).length + Object.keys(v.tools).length;
}

export function toSimTarget(
  choice: TargetChoice,
  agent: AgentDetail | undefined,
  graph: FlowGraph | undefined,
  tools: { id: string; description: string }[],
): SimTarget {
  if (choice.type === "version" && choice.versionId) return { type: "version", agent_version_id: choice.versionId };
  if (choice.type === "variant" && choice.variant && agent) {
    return {
      type: "variant",
      agent_version_id: agent.draft_version.id,
      label: choice.variant.label.trim() || "Variant",
      config: variantConfig(agent.draft_config, choice.variant, graph, tools) as unknown as Record<string, never>,
    };
  }
  return { type: choice.type === "variant" || choice.type === "version" ? "draft" : choice.type };
}

/** Everything a variant needs, loaded once for the dialogs. */
export function useTargetSources(agentId: string) {
  const agent = useAgent(agentId);
  const versions = useAgentVersions(agentId, !agent.isError);
  const flow = useFlowByAgent(agent.data?.type === "flow" ? agentId : undefined);
  const tools = useToolsByIds(agent.data?.draft_config.tool_ids ?? []);
  return { agent, versions, graph: flow.data?.graph, tools: tools.data ?? [] };
}

export function TargetPicker({
  agentId,
  value,
  onChange,
  id,
}: {
  agentId: string;
  value: TargetChoice;
  onChange: (c: TargetChoice) => void;
  id?: string;
}) {
  const agent = useAgent(agentId);
  const versions = useAgentVersions(agentId, !agent.isError);
  const a = agent.data;
  const published = a?.published_version ?? null;
  const options = useMemo(() => {
    const earlier = (versions.data?.items ?? []).filter((v) => !v.is_published && !v.is_draft).slice(0, 20);
    return [
      {
        value: "published",
        label: published ? `Published version, v${published.version_number}` : "Published version",
        disabled: Boolean(a) && !published,
      },
      { value: "draft", label: a ? `Saved draft, v${a.draft_version.version_number}` : "Saved draft" },
      ...earlier.map((v) => ({ value: `version:${v.id}`, label: `Version ${v.version_number}`, meta: v.note ?? undefined })),
      { value: "variant", label: "Variant: edit a copy of the draft", disabled: !a },
    ];
  }, [a, published, versions.data]);
  const current = value.type === "version" && value.versionId ? `version:${value.versionId}` : value.type;
  if (agent.isPending) return <Skeleton className="h-9 w-full" />;
  return (
    <Select
      id={id}
      value={current}
      onValueChange={(v) => {
        if (v.startsWith("version:")) onChange({ type: "version", versionId: v.slice(8), variant: null });
        else if (v === "variant") onChange({ type: "variant", versionId: null, variant: value.variant ?? emptyVariant(a?.draft_config) });
        else onChange({ type: v as TargetType, versionId: null, variant: null });
      }}
      options={options}
    />
  );
}

export function VariantEditor({
  agent,
  graph,
  tools,
  value,
  onChange,
}: {
  agent: AgentDetail;
  graph: FlowGraph | undefined;
  tools: { id: string; name: string; description: string }[];
  value: Variant;
  onChange: (v: Variant) => void;
}) {
  const base = agent.draft_config;
  const agentNodes = (graph?.nodes ?? []).filter((n) => n.type === "agent" || n.type === "task");
  const changes = variantChanges(base, value);
  const setMap = (key: "nodes" | "tools", id: string, text: string, original: string) => {
    const next = { ...value[key] };
    if (text === original) delete next[id];
    else next[id] = text;
    onChange({ ...value, [key]: next });
  };
  return (
    <section aria-label="Variant" className="flex flex-col gap-4 rounded-control border border-line bg-surface-2/50 p-4">
      <div className="flex items-center gap-2">
        <GitFork className="size-4 text-fg-3" aria-hidden />
        <span className="text-[13px] font-medium text-fg">Variant of the saved draft</span>
        <Badge tone={changes ? "accent" : "neutral"} className="ml-auto">
          {changes ? `${changes} ${changes === 1 ? "change" : "changes"}` : "No changes yet"}
        </Badge>
      </div>
      <Field label="Variant name" hint="Shown on the runs and the scorecard.">
        {({ id, describedBy }) => (
          <Input
            id={id}
            aria-describedby={describedBy}
            maxLength={60}
            value={value.label}
            placeholder="Shorter greeting"
            onChange={(e) => onChange({ ...value, label: e.target.value })}
          />
        )}
      </Field>
      {base.type === "single_prompt" && (
        <Field label="Prompt">
          {({ id }) => (
            <Textarea
              id={id}
              rows={8}
              className="text-[13px]"
              value={value.prompt}
              onChange={(e) => onChange({ ...value, prompt: e.target.value })}
            />
          )}
        </Field>
      )}
      {agentNodes.map((n) => {
        const original = "instructions" in n.config ? String(n.config.instructions ?? "") : "";
        return (
          <Field key={n.id} label={`Node: ${n.label || n.id}`}>
            {({ id }) => (
              <Textarea
                id={id}
                rows={4}
                className="text-[13px]"
                value={value.nodes[n.id] ?? original}
                onChange={(e) => setMap("nodes", n.id, e.target.value, original)}
              />
            )}
          </Field>
        );
      })}
      {tools.length > 0 && (
        <fieldset className="flex flex-col gap-3">
          <legend className="mb-2 text-[13px] font-medium text-fg">Tool descriptions</legend>
          {tools.map((t) => (
            <Field key={t.id} label={<span className="font-mono text-[12.5px]">{t.name}</span>}>
              {({ id }) => (
                <Textarea
                  id={id}
                  rows={2}
                  className="text-[13px]"
                  value={value.tools[t.id] ?? t.description}
                  onChange={(e) => setMap("tools", t.id, e.target.value, t.description)}
                />
              )}
            </Field>
          ))}
        </fieldset>
      )}
    </section>
  );
}
