import { ArrowRight, Bot, CircleAlert, Trash2, X } from "lucide-react";
import { memo } from "react";
import type { ConditionConfig, FlowEdge, FlowGraph, FlowNode, FlowRule, RuleOperator, ValidationIssue } from "../../../api/flows";
import { Field, IconButton, Input, Select, Textarea } from "../../../components";
import { NODE_META } from "../canvas/nodeMeta";
import { transitionDescription, transitionName } from "./transitionName";

const OPERATORS: { value: RuleOperator; label: string }[] = [
  { value: "equals", label: "equals" },
  { value: "not_equals", label: "does not equal" },
  { value: "contains", label: "contains" },
  { value: "matches", label: "matches pattern" },
  { value: "exists", label: "has a value" },
  { value: "gt", label: "is greater than" },
  { value: "lt", label: "is less than" },
];

const OUTCOME_COPY: Partial<Record<FlowEdge["trigger"], string>> = {
  always: "Followed as soon as the previous step finishes. No label or condition needed.",
  success: "Followed when the step succeeds.",
  failure: "Followed when the step fails or times out.",
  else: "Followed when no rule matches.",
};

/**
 * The selected connection (T029, T105, FR-020, FR-043, FR-044). Connections the model chooses
 * need a label and a condition and preview the exact choice the model sees; a classify
 * connection carries a category picked from the node's list; a rule connection holds its rule.
 * Memoised like the node panel: it only re-renders when the connection, the steps or its issues
 * change, so its scroll position and focus survive anything done on the canvas.
 */
export const EdgePanel = memo(function EdgePanel({
  edge,
  nodes,
  setGraph,
  issues,
  variables,
  onClose,
  onDelete,
  locked,
}: {
  edge: FlowEdge;
  nodes: FlowNode[];
  setGraph: (g: FlowGraph | ((g: FlowGraph) => FlowGraph)) => void;
  issues: ValidationIssue[];
  variables: string[];
  onClose: () => void;
  onDelete: (edge: FlowEdge) => void;
  locked: boolean;
}) {
  const source = nodes.find((n) => n.id === edge.source);
  const target = nodes.find((n) => n.id === edge.target);
  const update = (patch: Partial<FlowEdge>) => setGraph((g) => ({ ...g, edges: g.edges.map((e) => (e.id === edge.id ? { ...e, ...patch } : e)) }));
  const own = issues.filter((i) => i.edge_id === edge.id);
  const fieldIssue = (f: string) => own.find((i) => i.field === f)?.message ?? null;
  const name = transitionName(edge.label, edge.function_name);
  const labelTyped = (edge.label ?? "").length > 0;
  const labelError = labelTyped && !name ? "The label needs at least one letter or digit." : fieldIssue("label");
  const rule: FlowRule = edge.rule ?? { variable: "", operator: "equals", value: "" };
  const categories = source?.type === "condition" ? ((source.config as ConditionConfig).categories ?? []) : [];

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="panel-head flex items-start gap-3 border-b border-line px-5 py-4">
        <div className="min-w-0 flex-1">
          <p className="text-[11px] font-semibold text-fg-3">Connection</p>
          <p className="mt-1 flex min-w-0 items-center gap-1.5 text-[14px] font-semibold text-fg">
            <span className="flex min-w-0 items-center gap-1.5" data-ntype={source?.type}>
              <span className="fnode-chip !size-6 !rounded-[7px] [&_svg]:!size-3.5">{source && NODE_META[source.type].icon}</span>
              <span className="truncate">{source?.label ?? "Missing step"}</span>
            </span>
            <ArrowRight className="size-3.5 shrink-0 text-fg-3" aria-hidden />
            <span className="flex min-w-0 items-center gap-1.5" data-ntype={target?.type}>
              <span className="fnode-chip !size-6 !rounded-[7px] [&_svg]:!size-3.5">{target && NODE_META[target.type].icon}</span>
              <span className="truncate">{target?.label ?? "Missing step"}</span>
            </span>
          </p>
        </div>
        <IconButton label="Delete connection" className="size-8 hover:text-danger-text" disabled={locked} onClick={() => onDelete(edge)}>
          <Trash2 className="size-4" aria-hidden />
        </IconButton>
        <IconButton label="Close settings" className="size-8" onClick={onClose}>
          <X className="size-4" aria-hidden />
        </IconButton>
      </header>
      {/* The scroll area is a plain block: as a flex column its children would shrink to fit and
          clip (the preview below used to be cut off) instead of overflowing and scrolling. */}
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain" data-panel-scroll>
        <fieldset disabled={locked} className="flex min-w-0 flex-col gap-5 px-5 pb-8 pt-5">
          {edge.trigger === "llm_condition" && (
            <>
              <Field label="Label" hint="A few words, such as Billing question." error={labelError}>
                {({ id, describedBy, invalid }) => (
                  <Input
                    id={id}
                    autoFocus={!edge.label}
                    value={edge.label ?? ""}
                    maxLength={60}
                    onChange={(e) => update({ label: e.target.value })}
                    aria-describedby={describedBy}
                    aria-invalid={invalid || undefined}
                  />
                )}
              </Field>
              <Field
                label="When should the agent take it?"
                hint="Plain language, such as: the caller asks about a bill."
                error={fieldIssue("condition")}
              >
                {({ id, describedBy, invalid }) => (
                  <Textarea
                    id={id}
                    rows={3}
                    maxLength={1000}
                    value={edge.condition ?? ""}
                    onChange={(e) => update({ condition: e.target.value })}
                    aria-describedby={describedBy}
                    aria-invalid={invalid || undefined}
                  />
                )}
              </Field>
              <section
                aria-label="How the agent sees this"
                className="shrink-0 overflow-hidden rounded-panel border border-line bg-console text-console-fg shadow-1"
              >
                <p className="flex items-center gap-1.5 border-b border-console-line px-3.5 py-2 text-[12px] font-medium text-console-fg-2">
                  <Bot className="size-3.5" aria-hidden /> How the agent sees this
                </p>
                <div className="px-3.5 py-3">
                  <p className="font-mono text-[13px] text-[#a3adff]">{name ?? "route_to_..."}()</p>
                  <p className="mt-1.5 text-[13px] leading-relaxed text-console-fg-2">
                    {transitionDescription(target?.label ?? "the next step", edge.condition)}
                  </p>
                </div>
              </section>
            </>
          )}
          {edge.trigger === "category" && (
            <>
              <Field label="Category" error={fieldIssue("category")}>
                {({ id }) => (
                  <Select
                    id={id}
                    value={edge.category ?? ""}
                    placeholder="Choose a category"
                    onValueChange={(category) => update({ category })}
                    options={categories.map((c) => ({ value: c.name, label: c.name }))}
                  />
                )}
              </Field>
              <p className="rounded-control bg-surface-2 px-3 py-2.5 text-[13px] leading-relaxed text-fg-2">
                {source?.label ?? "The condition"} decides the route by reading the conversation, so this connection needs no condition of its own.
                Rename the category on the node and this connection follows.
              </p>
            </>
          )}
          {edge.trigger === "rule" && (
            <>
              <Field label="Variable" hint="Set by an earlier step, such as task_result.age." error={fieldIssue("rule.variable")}>
                {({ id, describedBy, invalid }) => (
                  <>
                    <Input
                      id={id}
                      list={`${id}-vars`}
                      className="font-mono"
                      value={rule.variable}
                      onChange={(e) => update({ rule: { ...rule, variable: e.target.value } })}
                      aria-describedby={describedBy}
                      aria-invalid={invalid || undefined}
                    />
                    <datalist id={`${id}-vars`}>
                      {variables.map((v) => (
                        <option key={v} value={v} />
                      ))}
                    </datalist>
                  </>
                )}
              </Field>
              <Field label="Check">
                {({ id }) => (
                  <Select
                    id={id}
                    value={rule.operator}
                    onValueChange={(operator) =>
                      update({ rule: { ...rule, operator: operator as RuleOperator, value: operator === "exists" ? null : (rule.value ?? "") } })
                    }
                    options={OPERATORS}
                  />
                )}
              </Field>
              {rule.operator !== "exists" && (
                <Field
                  label="Value"
                  error={fieldIssue("rule.value")}
                  hint={rule.operator === "matches" ? "A regular expression that must match the whole value." : undefined}
                >
                  {({ id, describedBy, invalid }) => (
                    <Input
                      id={id}
                      value={rule.value ?? ""}
                      onChange={(e) => update({ rule: { ...rule, value: e.target.value } })}
                      aria-describedby={describedBy}
                      aria-invalid={invalid || undefined}
                    />
                  )}
                </Field>
              )}
            </>
          )}
          {OUTCOME_COPY[edge.trigger] && (
            <p className="rounded-control bg-surface-2 px-3 py-2.5 text-[13px] leading-relaxed text-fg-2">{OUTCOME_COPY[edge.trigger]}</p>
          )}
          {own
            .filter((i) => !i.field)
            .map((i, k) => (
              <p key={k} className="flex items-start gap-2 text-[13px] text-danger-text">
                <CircleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />
                {i.message}
              </p>
            ))}
        </fieldset>
      </div>
    </div>
  );
});
