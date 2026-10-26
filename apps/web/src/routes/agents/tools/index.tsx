/**
 * Registers the agent editor's Tools tab (spec 005, T005). Imported once by app/router.tsx; the
 * tab's code loads when it is first opened.
 */
import { Wrench } from "lucide-react";
import { lazy, Suspense } from "react";
import { Skeleton } from "../../../components";
import { registerEditorPanel, type EditorPanelProps } from "../editor/panelSlots";

const ToolsTab = lazy(() => import("./ToolsTab").then((m) => ({ default: m.ToolsTab })));

function LazyToolsTab(props: EditorPanelProps) {
  return (
    <Suspense fallback={<Skeleton className="h-[260px] w-full rounded-panel" />}>
      <ToolsTab {...props} />
    </Suspense>
  );
}

registerEditorPanel({ id: "tools", label: "Tools", icon: <Wrench aria-hidden />, component: LazyToolsTab });
