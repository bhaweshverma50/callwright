import { Panel, useReactFlow } from "@xyflow/react";
import { Maximize, Minus, Network, Plus, Redo2, Undo2 } from "lucide-react";
import { IconButton } from "../../../components";
import { fitOptions } from "./layout";

/**
 * Canvas toolbar (FR-040, T101): Auto-layout, Fit to screen, zoom in and out, undo and redo.
 * Every control is icon-only with an accessible name and a visible tooltip.
 */
export function CanvasToolbar({
  onLayout,
  onViewChanged,
  onUndo,
  onRedo,
  canUndo,
  canRedo,
}: {
  onLayout: () => void;
  onViewChanged: () => void;
  onUndo: () => void;
  onRedo: () => void;
  canUndo: boolean;
  canRedo: boolean;
}) {
  const flow = useReactFlow();
  return (
    <Panel position="bottom-center" className="!m-3 sm:!m-4">
      <div
        role="toolbar"
        aria-label="Canvas"
        className="flex items-center gap-0.5 rounded-full border border-line bg-surface/90 p-1 shadow-pop backdrop-blur-md"
      >
        <IconButton label="Auto-layout" tooltipSide="top" className="size-8 rounded-full" onClick={onLayout}>
          <Network className="size-4" aria-hidden />
        </IconButton>
        <IconButton
          label="Fit to screen"
          className="size-8 rounded-full"
          onClick={() => void flow.fitView({ ...fitOptions(), duration: 320 }).then(onViewChanged)}
        >
          <Maximize className="size-4" aria-hidden />
        </IconButton>
        <span aria-hidden className="mx-1 h-5 w-px bg-line" />
        <IconButton label="Zoom out" className="size-8 rounded-full" onClick={() => void flow.zoomOut({ duration: 200 }).then(onViewChanged)}>
          <Minus className="size-4" aria-hidden />
        </IconButton>
        <IconButton label="Zoom in" className="size-8 rounded-full" onClick={() => void flow.zoomIn({ duration: 200 }).then(onViewChanged)}>
          <Plus className="size-4" aria-hidden />
        </IconButton>
        <span aria-hidden className="mx-1 h-5 w-px bg-line" />
        <IconButton label="Undo" className="size-8 rounded-full" disabled={!canUndo} onClick={onUndo}>
          <Undo2 className="size-4" aria-hidden />
        </IconButton>
        <IconButton label="Redo" className="size-8 rounded-full" disabled={!canRedo} onClick={onRedo}>
          <Redo2 className="size-4" aria-hidden />
        </IconButton>
      </div>
    </Panel>
  );
}
