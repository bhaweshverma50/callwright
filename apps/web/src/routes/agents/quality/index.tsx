/**
 * Registers the agent editor's Quality tab (spec 007, T023, T042). Imported once by
 * app/router.tsx; the tab's code loads when it is first opened. Both agent types get it: the
 * flow builder renders registered panels in its settings drawer.
 */
import { ShieldCheck } from "lucide-react";
import { lazy, Suspense } from "react";
import { Skeleton } from "../../../components";
import { registerEditorPanel, type EditorPanelProps } from "../editor/panelSlots";

const QualityTab = lazy(() => import("./QualityTab").then((m) => ({ default: m.QualityTab })));

function LazyQualityTab(props: EditorPanelProps) {
  return (
    <Suspense fallback={<Skeleton className="h-[320px] w-full rounded-panel" />}>
      <QualityTab {...props} />
    </Suspense>
  );
}

registerEditorPanel({ id: "quality", label: "Quality", icon: <ShieldCheck aria-hidden />, component: LazyQualityTab });
