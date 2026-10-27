import { Panel } from "@xyflow/react";
import { Plus } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { memo, useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import type { NodeType } from "../../../api/flows";
import { cn, focusRing } from "../../../components";
import { DRAG_TYPE, NODE_META, PALETTE_GROUPS } from "./nodeMeta";

/**
 * Node palette (T026): one "Add step" button on the canvas that opens a short, grouped and
 * labelled list of the nine step types (a column per group on wider canvases). Drag a step onto the canvas, or click it to drop it in
 * the middle of the view. Arrow keys move through the list, Escape closes it.
 */
export const Palette = memo(function Palette({ onAdd, disabled }: { onAdd: (type: NodeType) => void; disabled?: boolean }) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const listId = useId();

  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (root.current && !root.current.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("pointerdown", onDown);
    return () => window.removeEventListener("pointerdown", onDown);
  }, [open]);

  useEffect(() => {
    if (open) root.current?.querySelector<HTMLButtonElement>("[data-ntype]")?.focus({ preventScroll: true });
  }, [open]);

  const close = (refocus: boolean) => {
    setOpen(false);
    if (refocus) trigger.current?.focus();
  };

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Escape") {
      e.stopPropagation();
      close(true);
      return;
    }
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    const items = Array.from(root.current?.querySelectorAll<HTMLButtonElement>("[data-ntype]") ?? []);
    const at = items.indexOf(document.activeElement as HTMLButtonElement);
    if (at < 0) return;
    e.preventDefault();
    items[(at + (e.key === "ArrowDown" ? 1 : items.length - 1)) % items.length]?.focus();
  };

  return (
    <Panel position="top-left" className="!m-3 sm:!m-4">
      <div ref={root} className="relative" onKeyDown={onKeyDown}>
        <button
          ref={trigger}
          type="button"
          aria-expanded={open}
          aria-controls={listId}
          disabled={disabled}
          onClick={() => setOpen((o) => !o)}
          className={cn(
            "palette-trigger group inline-flex h-9 cursor-pointer items-center gap-2 rounded-full pl-1.5 pr-3.5 text-[13px] font-medium",
            "disabled:cursor-not-allowed disabled:opacity-55",
            focusRing,
          )}
        >
          <span className="palette-trigger-icon grid size-6 place-items-center rounded-full" aria-hidden>
            <Plus className={cn("size-3.5 transition-transform duration-200", open && "rotate-45")} strokeWidth={2.4} />
          </span>
          Add step
        </button>
        <AnimatePresence>
          {open && (
            <motion.div
              id={listId}
              initial={{ opacity: 0, y: -6, scale: 0.97 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: -4, scale: 0.98, transition: { duration: 0.12 } }}
              transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }}
              style={{ transformOrigin: "top left" }}
              className="palette-menu absolute left-0 top-[calc(100%+8px)] z-20 w-[300px] max-w-[calc(100cqw-24px)] sm:w-[612px] sm:max-w-[calc(100cqw-32px)] overflow-y-auto rounded-panel p-1.5"
            >
              <div className="grid grid-cols-1 gap-x-1 sm:grid-cols-3">
                {PALETTE_GROUPS.map((group) => (
                  <section key={group.title} aria-label={group.title} className="py-1 sm:py-0.5">
                    <h3 className="px-2.5 pb-1 pt-1.5 text-[12px] font-medium text-fg-3">{group.title}</h3>
                    <ul className="flex flex-col">
                      {group.types.map((type) => {
                        const meta = NODE_META[type];
                        return (
                          <li key={type}>
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
                              onDragEnd={() => setOpen(false)}
                              onClick={() => {
                                onAdd(type);
                                setOpen(false);
                              }}
                              className={cn(
                                "palette-item group flex h-full w-full cursor-grab items-start gap-3 rounded-control px-2.5 py-2 text-left active:cursor-grabbing",
                                "disabled:cursor-not-allowed disabled:opacity-50",
                                focusRing,
                              )}
                            >
                              <span className="fnode-chip mt-0.5 transition-transform duration-200 group-hover:scale-105" aria-hidden>
                                {meta.icon}
                              </span>
                              <span className="min-w-0 flex-1">
                                <span className="block text-[13.5px] font-medium leading-tight text-fg">{meta.title}</span>
                                <span className="mt-0.5 line-clamp-2 block text-[12px] leading-snug text-fg-3">{meta.blurb}</span>
                              </span>
                            </button>
                          </li>
                        );
                      })}
                    </ul>
                  </section>
                ))}
              </div>
              <p className="mx-1 mt-1 border-t border-line px-1.5 pb-1 pt-2 text-[11.5px] text-fg-3">Click to add, or drag onto the canvas.</p>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </Panel>
  );
});
