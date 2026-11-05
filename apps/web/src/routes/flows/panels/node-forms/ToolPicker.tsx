import { Check, Plus, Wrench } from "lucide-react";
import { useTools } from "../../../../api/tools";
import { Button, Skeleton, cn, focusRing } from "../../../../components";
import { TOOL_META } from "../../../agents/tools/toolMeta";
import { Group } from "./shared";

/**
 * Node tools (FR-011, FR-053, T082, T112): pick from the workspace library; these are added to
 * the flow-wide tools for this step only. With an empty library the section stays, with a
 * shortcut to create a tool.
 */
export function ToolPicker({ value, onChange, onCreateTool }: { value: string[]; onChange: (ids: string[]) => void; onCreateTool: () => void }) {
  const tools = useTools("", null, 1, 50);
  const items = tools.data?.items ?? [];
  const toggle = (id: string) => onChange(value.includes(id) ? value.filter((v) => v !== id) : [...value, id]);
  return (
    <Group title="Tools for this step" icon={<Wrench aria-hidden />} description="Flow-wide tools are always available; these only here.">
      {tools.isLoading ? (
        <Skeleton className="h-16 w-full" />
      ) : items.length === 0 ? (
        <div className="flex flex-col items-start gap-2.5 rounded-control border border-dashed border-line-strong px-3.5 py-3.5">
          <p className="text-[13px] leading-relaxed text-fg-3">
            No tools in this workspace yet. Tools let a step look things up, transfer or end the call.
          </p>
          <Button size="sm" icon={<Plus aria-hidden />} onClick={onCreateTool}>
            Create a tool
          </Button>
        </div>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {items.map((t) => {
            const on = value.includes(t.id);
            return (
              <li key={t.id}>
                <button
                  type="button"
                  aria-pressed={on}
                  onClick={() => toggle(t.id)}
                  className={cn(
                    "flex w-full cursor-pointer items-center gap-2.5 rounded-control border px-2.5 py-2 text-left transition-[background-color,border-color] duration-150",
                    on ? "border-accent/50 bg-accent-soft/60" : "border-line bg-surface hover:border-line-strong",
                    focusRing,
                  )}
                >
                  <span className="text-fg-3 [&_svg]:size-4">{TOOL_META[t.type].icon}</span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-mono text-[13px] text-fg">{t.name}</span>
                    <span className="block truncate text-[12px] text-fg-3">{t.description}</span>
                  </span>
                  <span
                    className={cn(
                      "grid size-5 place-items-center rounded-full border transition-[transform,background-color] duration-200",
                      on ? "bg-accent scale-100 border-transparent text-white" : "scale-90 border-line-strong text-transparent",
                    )}
                    aria-hidden
                  >
                    <Check strokeWidth={3} className="size-3" />
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </Group>
  );
}
