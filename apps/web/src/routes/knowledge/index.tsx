/**
 * Knowledge routes (spec 005, T005): /knowledge-base and /knowledge-base/:id, plus the agent
 * editor's Knowledge tab. Imported once by app/router.tsx; pages load on demand.
 */
import { BookOpen } from "lucide-react";
import { lazy, Suspense } from "react";
import type { RouteObject } from "react-router";
import { Skeleton } from "../../components";
import { registerEditorPanel, type EditorPanelProps } from "../agents/editor/panelSlots";

const KnowledgeListPage = lazy(() => import("./KnowledgeListPage").then((m) => ({ default: m.KnowledgeListPage })));
const KnowledgeBasePage = lazy(() => import("./KnowledgeBasePage").then((m) => ({ default: m.KnowledgeBasePage })));
const KnowledgeTab = lazy(() => import("./components/AgentKnowledgePicker").then((m) => ({ default: m.KnowledgeTab })));

export const knowledgeRoutes: RouteObject[] = [
  { path: "knowledge-base", element: <KnowledgeListPage /> },
  { path: "knowledge-base/:id", element: <KnowledgeBasePage /> },
];

function LazyKnowledgeTab(props: EditorPanelProps) {
  return (
    <Suspense fallback={<Skeleton className="h-[220px] w-full rounded-panel" />}>
      <KnowledgeTab {...props} />
    </Suspense>
  );
}

registerEditorPanel({ id: "knowledge", label: "Knowledge", icon: <BookOpen aria-hidden />, component: LazyKnowledgeTab });
