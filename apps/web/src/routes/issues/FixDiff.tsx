/**
 * Before and after of a fix, per kind (T033). Text replacements show a line diff (removed lines
 * then added lines, unchanged lines dimmed); additions show the new rule, transition or tools;
 * an advisory knowledge fix lists the topics nothing covers.
 */
import { ArrowRight, BookX, Plus } from "lucide-react";
import type { ReactNode } from "react";
import type { FixKind, FixPayload } from "../../api/issues";
import { cn } from "../../components";
import { diffStats, lineDiff } from "../../lib/lineDiff";

export function TextDiff({ before, after, label }: { before: string; after: string; label: string }) {
  const lines = lineDiff(before, after);
  const { added, removed } = diffStats(lines);
  return (
    <figure className="flex min-w-0 flex-col gap-1.5">
      <figcaption className="flex flex-wrap items-baseline justify-between gap-2 text-[13px] text-fg-3">
        <span>{label}</span>
        <span className="font-mono tnum">
          <span className="text-success-text">+{added}</span> <span className="text-danger-text">-{removed}</span>
        </span>
      </figcaption>
      <div
        role="table"
        aria-label={`${label}, before and after`}
        className="overflow-hidden rounded-control border border-line bg-surface-2/60 font-mono text-[13px]"
      >
        {lines.map((l, k) => (
          <div
            role="row"
            key={k}
            className={cn(
              "grid grid-cols-[20px_minmax(0,1fr)] gap-1 px-2 py-[3px] leading-relaxed",
              l.kind === "add" && "bg-success-soft text-success-text",
              l.kind === "remove" && "bg-danger-soft text-danger-text",
              l.kind === "same" && "text-fg-2",
            )}
          >
            <span
              role="cell"
              aria-label={l.kind === "add" ? "Added" : l.kind === "remove" ? "Removed" : "Unchanged"}
              className="select-none text-center opacity-70"
            >
              {l.kind === "add" ? "+" : l.kind === "remove" ? "-" : " "}
            </span>
            <span role="cell" className="whitespace-pre-wrap break-words">
              {l.text || " "}
            </span>
          </div>
        ))}
      </div>
    </figure>
  );
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5">
      <span className="text-[12px] text-fg-3">{label}</span>
      <span className="min-w-0 break-words text-[13px] text-fg">{children}</span>
    </div>
  );
}

function Added({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <span className="flex items-center gap-1.5 text-[13px] text-fg-3">
        <Plus className="size-3.5 text-success-text" aria-hidden />
        {label}
      </span>
      <div className="whitespace-pre-wrap break-words rounded-control border border-line bg-success-soft px-3 py-2 text-[13px] leading-relaxed text-fg">
        {children}
      </div>
    </div>
  );
}

const Mono = ({ children }: { children: ReactNode }) => <span className="break-all font-mono text-[13px]">{children}</span>;

const PLACEMENT = { agent_prompt: "the agent prompt", node: "one node", all_agent_nodes: "every agent node" } as const;

export function FixDiff({ kind, payload }: { kind: FixKind; payload: FixPayload }) {
  const p = payload as Record<string, unknown>;
  const str = (k: string) => String(p[k] ?? "");
  const list = (k: string) => (Array.isArray(p[k]) ? (p[k] as string[]) : []);
  switch (kind) {
    case "prompt_edit":
      return <TextDiff label="Agent prompt" before={str("current_prompt")} after={str("proposed_prompt")} />;
    case "node_prompt_edit":
      return (
        <TextDiff
          label={`Instructions of ${str("node_label") || str("node_id")}`}
          before={str("current_instructions")}
          after={str("proposed_instructions")}
        />
      );
    case "tool_description_edit":
      return (
        <TextDiff
          label={`Description of ${str("tool_name") || str("tool_id")}`}
          before={str("current_description")}
          after={str("proposed_description")}
        />
      );
    case "transition_condition_edit":
      return (
        <TextDiff label={`Condition of ${str("edge_label") || str("edge_id")}`} before={str("current_condition")} after={str("proposed_condition")} />
      );
    case "add_guardrail": {
      const placement = (p.placement as keyof typeof PLACEMENT) ?? "agent_prompt";
      const where = placement === "node" ? `node ${str("node_id")}` : PLACEMENT[placement];
      return <Added label={`Rule added to ${where}`}>{str("rule_text")}</Added>;
    }
    case "add_transition":
      return (
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-2 text-[13px] text-fg">
            <Mono>{str("source_node_id")}</Mono>
            <ArrowRight className="size-3.5 text-fg-3" aria-label="to" />
            <Mono>{str("target_node_id")}</Mono>
            <span className="text-fg-3">as</span>
            <Mono>{str("edge_label")}</Mono>
          </div>
          <Added label="Moves along when">{str("handoff_condition")}</Added>
        </div>
      );
    case "node_tool_attachment":
      return (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Fact label={`Attach to ${str("node_id")}`}>
            {list("tools_to_attach").length ? <Mono>{list("tools_to_attach").join(", ")}</Mono> : "None"}
          </Fact>
          <Fact label="Detach">{list("tools_to_detach").length ? <Mono>{list("tools_to_detach").join(", ")}</Mono> : "None"}</Fact>
        </div>
      );
    case "kb_attach": {
      const kbs = list("kb_ids_to_attach");
      const topics = list("uncovered_topics");
      return (
        <div className="flex flex-col gap-3">
          {kbs.length > 0 && <Fact label="Knowledge bases to attach">{<Mono>{kbs.join(", ")}</Mono>}</Fact>}
          {topics.length > 0 && (
            <div className="flex flex-col gap-1.5">
              <span className="flex items-center gap-1.5 text-[13px] text-fg-3">
                <BookX className="size-3.5 text-warning-text" aria-hidden />
                Topics no knowledge base covers
              </span>
              <ul className="flex flex-wrap gap-1.5">
                {topics.map((t) => (
                  <li key={t} className="rounded-full border border-line bg-surface px-2.5 py-1 text-[13px] text-fg">
                    {t}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      );
    }
  }
}

/** The editable text of a fix, and a payload with that text replaced (manual edit). */
export const EDITABLE: Partial<Record<FixKind, { field: string; label: string }>> = {
  prompt_edit: { field: "proposed_prompt", label: "Proposed prompt" },
  node_prompt_edit: { field: "proposed_instructions", label: "Proposed instructions" },
  add_guardrail: { field: "rule_text", label: "Rule" },
  tool_description_edit: { field: "proposed_description", label: "Proposed description" },
  transition_condition_edit: { field: "proposed_condition", label: "Proposed condition" },
  add_transition: { field: "handoff_condition", label: "Moves along when" },
};
