import { Panel } from "@xyflow/react";
import type { NodeType } from "../../../api/flows";
import { Tooltip, cn, focusRing } from "../../../components";
import { DRAG_TYPE, NODE_META, PALETTE } from "./nodeMeta";

/**
 * Node palette (T026): a slim rail of step types on the canvas edge. Drag one onto the canvas,
 * or click it to drop it in the middle of the view. Each tile names the step in a tooltip.
 */
export function Palette({ onAdd, disabled }: { onAdd: (type: NodeType) => void; disabled?: boolean }) {
  return (
    <Panel position="top-left" className="!m-3 sm:!m-4">
      <ul
        aria-label="Add a step"
        className="flex gap-1 rounded-panel border border-line bg-surface/92 p-1.5 shadow-pop backdrop-blur-md max-sm:max-w-[calc(100vw-72px)] max-sm:overflow-x-auto max-sm:[scrollbar-width:none] sm:flex-col"
      >
        {PALETTE.map((type) => {
          const meta = NODE_META[type];
          return (
            <li key={type} className="shrink-0">
              <Tooltip
                side="right"
                content={
                  <span className="flex flex-col">
                    <span className="font-medium">Add {meta.title}</span>
                    <span className="opacity-75">{meta.blurb}</span>
                  </span>
                }
              >
                <button
                  type="button"
                  aria-label={`Add ${meta.title}`}
                  draggable={!disabled}
                  disabled={disabled}
                  data-ntype={type}
                  onDragStart={(e) => {
                    e.dataTransfer.setData(DRAG_TYPE, type);
                    e.dataTransfer.effectAllowed = "move";
                  }}
                  onClick={() => onAdd(type)}
                  className={cn(
                    "palette-tile group grid size-10 cursor-grab place-items-center rounded-control transition-[background-color,transform] duration-150",
                    "hover:bg-surface-2 active:scale-95 active:cursor-grabbing disabled:cursor-not-allowed disabled:opacity-50",
                    focusRing,
                  )}
                >
                  <span className="fnode-chip transition-transform duration-200 group-hover:scale-110" aria-hidden>
                    {meta.icon}
                  </span>
                </button>
              </Tooltip>
            </li>
          );
        })}
      </ul>
    </Panel>
  );
}
