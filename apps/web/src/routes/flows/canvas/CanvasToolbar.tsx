import { Panel, useReactFlow, useStore } from "@xyflow/react";
import { Maximize, Minus, Network, Plus, Redo2, Undo2 } from "lucide-react";
import { memo } from "react";
import { IconButton, Tooltip, cn, focusRing } from "../../../components";
import { fitOptions } from "./layout";

const BTN = "size-8 rounded-full text-fg-2 hover:text-fg";

/**
 * Canvas toolbar (FR-040, T101): Auto-layout, Fit to screen, zoom out, the zoom level (click for
 * 100%), zoom in, undo and redo. A light pill in the bottom-left corner; every icon-only control
 * has an accessible name and a visible tooltip. Only the zoom readout follows the viewport, so
 * panning never re-renders the toolbar.
 */
export const CanvasToolbar = memo(function CanvasToolbar({
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
  const zoom = useStore((s) => Math.round(s.transform[2] * 100));
  return (
    <Panel position="bottom-left" className="!m-3 sm:!m-4">
      <div role="toolbar" aria-label="Canvas" className="canvas-toolbar flex items-center gap-0.5 rounded-full p-1">
        <IconButton label="Auto-layout" tooltipSide="top" className={BTN} onClick={onLayout}>
          <Network className="size-4" aria-hidden />
        </IconButton>
        <IconButton
          label="Fit to screen"
          tooltipSide="top"
          className={BTN}
          onClick={() => void flow.fitView({ ...fitOptions(), duration: 320 }).then(onViewChanged)}
        >
          <Maximize className="size-4" aria-hidden />
        </IconButton>
        <span aria-hidden className="mx-1 h-4 w-px bg-line" />
        <IconButton label="Zoom out" tooltipSide="top" className={BTN} onClick={() => void flow.zoomOut({ duration: 200 }).then(onViewChanged)}>
          <Minus className="size-4" aria-hidden />
        </IconButton>
        <Tooltip side="top" content="Zoom to 100%">
          <button
            type="button"
            aria-label={`Zoom ${zoom}%, zoom to 100%`}
            onClick={() => void flow.zoomTo(1, { duration: 220 }).then(onViewChanged)}
            className={cn(
              "h-8 min-w-[3.25rem] cursor-pointer rounded-full px-1.5 font-mono text-[12px] tabular-nums text-fg-2 transition-colors hover:bg-surface-3 hover:text-fg",
              focusRing,
            )}
          >
            {zoom}%
          </button>
        </Tooltip>
        <IconButton label="Zoom in" tooltipSide="top" className={BTN} onClick={() => void flow.zoomIn({ duration: 200 }).then(onViewChanged)}>
          <Plus className="size-4" aria-hidden />
        </IconButton>
        <span aria-hidden className="mx-1 h-4 w-px bg-line" />
        <IconButton label="Undo" tooltipSide="top" className={BTN} disabled={!canUndo} onClick={onUndo}>
          <Undo2 className="size-4" aria-hidden />
        </IconButton>
        <IconButton label="Redo" tooltipSide="top" className={BTN} disabled={!canRedo} onClick={onRedo}>
          <Redo2 className="size-4" aria-hidden />
        </IconButton>
      </div>
    </Panel>
  );
});
