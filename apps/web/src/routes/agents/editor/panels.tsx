/**
 * Extra agent editor tabs (T097, FR-043): tools (005), knowledge (005) and quality checks (007).
 * The single-prompt editor shows each as a tab and the flow builder's settings drawer shows them as
 * sections, so both agent types get the same panels. Each tab's code loads when it is first opened.
 */
import { BookOpen, ShieldCheck, Wrench } from "lucide-react";
import { lazy, Suspense, type ComponentType, type ReactNode } from "react";
import type { AgentConfig, AgentType } from "../../../api/agents";
import { Skeleton } from "../../../components";

export interface EditorPanelProps {
  agentId: string | null;
  agentType: AgentType;
  config: AgentConfig;
  /** Applies a change to the draft (marks the editor unsaved). */
  update: (mutate: (draft: AgentConfig) => void) => void;
}

export interface EditorPanel {
  id: "tools" | "knowledge" | "quality";
  label: string;
  icon: ReactNode;
  component: ComponentType<EditorPanelProps>;
}

function lazyTab(load: () => Promise<ComponentType<EditorPanelProps>>, skeletonHeight: string): ComponentType<EditorPanelProps> {
  const Tab = lazy(() => load().then((component) => ({ default: component })));
  return function LazyTab(props: EditorPanelProps) {
    return (
      <Suspense fallback={<Skeleton className={`${skeletonHeight} w-full rounded-panel`} />}>
        <Tab {...props} />
      </Suspense>
    );
  };
}

/** In tab order. */
export const EDITOR_PANELS: EditorPanel[] = [
  {
    id: "tools",
    label: "Tools",
    icon: <Wrench aria-hidden />,
    component: lazyTab(() => import("../tools/ToolsTab").then((m) => m.ToolsTab), "h-[260px]"),
  },
  {
    id: "knowledge",
    label: "Knowledge",
    icon: <BookOpen aria-hidden />,
    component: lazyTab(() => import("../knowledge/AgentKnowledgePicker").then((m) => m.KnowledgeTab), "h-[220px]"),
  },
  {
    id: "quality",
    label: "Quality",
    icon: <ShieldCheck aria-hidden />,
    component: lazyTab(() => import("../quality/QualityTab").then((m) => m.QualityTab), "h-[320px]"),
  },
];
