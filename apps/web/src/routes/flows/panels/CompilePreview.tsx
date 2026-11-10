import { Cpu, MessageSquareText, Wrench } from "lucide-react";
import type { CompileResult } from "../../../api/flows";
import { Badge } from "../../../components";
import { NODE_META } from "../canvas/nodeMeta";

type CompiledNode = NonNullable<CompileResult["compiled"]>["nodes"][string];

// The contract types a compiled step's type, label and transitions; the rest of a step is open
// (data-model.md section 4), so the preview reads the parts it shows with checks.
const record = (v: unknown): Record<string, unknown> | null => (v && typeof v === "object" ? (v as Record<string, unknown>) : null);
const instructionsOf = (n: CompiledNode) => (typeof n.instructions === "string" ? n.instructions : "");
const modelOf = (n: CompiledNode) => {
  const model = record(n.llm)?.model;
  return typeof model === "string" ? model : null;
};
const toolNamesOf = (n: CompiledNode) =>
  (Array.isArray(n.tools) ? n.tools : []).map((t) => record(t)?.name).filter((name): name is string => typeof name === "string");

/** What each conversational step's model receives (FR-030, T045). */
export function CompilePreview({ result }: { result: CompileResult }) {
  if (!result.compiled) return <p className="text-[13px] text-danger-text">The flow has errors, so there is nothing to preview yet.</p>;
  const nodes = Object.entries(result.compiled.nodes).filter(([, n]) => n.type === "agent" || n.type === "task");
  return (
    <div className="flex flex-col gap-3">
      {nodes.map(([id, n]) => (
        <article key={id} className="overflow-hidden rounded-panel border border-line" data-ntype={n.type}>
          <header className="flex items-center gap-2.5 border-b border-line bg-surface-2/60 px-4 py-2.5">
            <span className="fnode-chip !size-7" aria-hidden>
              {NODE_META[n.type].icon}
            </span>
            <span className="min-w-0 flex-1 truncate text-[14px] font-semibold">{n.label}</span>
            {modelOf(n) && (
              <Badge icon={<Cpu />} className="font-mono">
                {modelOf(n)}
              </Badge>
            )}
          </header>
          <div className="flex flex-col gap-3 px-4 py-3">
            <p className="flex items-center gap-1.5 text-[12px] font-medium text-fg-3">
              <MessageSquareText className="size-3.5" aria-hidden /> Instructions
            </p>
            <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded-control bg-console px-3 py-2.5 font-mono text-[12px] leading-relaxed text-console-fg">
              {instructionsOf(n) || "(empty)"}
            </pre>
            {(n.transitions?.length ?? 0) + toolNamesOf(n).length > 0 && (
              <>
                <p className="flex items-center gap-1.5 text-[12px] font-medium text-fg-3">
                  <Wrench className="size-3.5" aria-hidden /> Choices and tools
                </p>
                <ul className="flex flex-col gap-1">
                  {n.transitions?.map((t) => (
                    <li key={t.function_name} className="text-[12px]">
                      <span className="font-mono text-accent-text">{t.function_name}</span> <span className="text-fg-3">{t.description}</span>
                    </li>
                  ))}
                  {toolNamesOf(n).map((name) => (
                    <li key={name} className="font-mono text-[12px] text-fg-2">
                      {name}
                    </li>
                  ))}
                </ul>
              </>
            )}
          </div>
        </article>
      ))}
    </div>
  );
}
