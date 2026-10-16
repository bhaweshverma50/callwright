/**
 * Editor panel slots (T097, FR-043). Feature 007 registers its post-call analysis variables and
 * quality checks panels here; the single-prompt editor (and 004's flow builder) render every
 * registered panel as an extra tab, so both agent types get the same panels.
 *
 *   registerEditorPanel({ id: "analysis", label: "Post-call analysis", icon: <ChartBar />, component: AnalysisPanel });
 */
import type { ComponentType, ReactNode } from "react";
import type { AgentConfig, AgentType } from "../../../api/agents";

export interface EditorPanelProps {
  agentId: string | null;
  agentType: AgentType;
  config: AgentConfig;
  /** Applies a change to the draft (marks the editor unsaved). */
  update: (mutate: (draft: AgentConfig) => void) => void;
}

export interface EditorPanel {
  id: string;
  label: string;
  icon?: ReactNode;
  /** Which agent types show the panel (default both). */
  types?: AgentType[];
  component: ComponentType<EditorPanelProps>;
}

const panels = new Map<string, EditorPanel>();

export function registerEditorPanel(panel: EditorPanel) {
  panels.set(panel.id, panel);
}

export function editorPanels(type: AgentType): EditorPanel[] {
  return [...panels.values()].filter((p) => !p.types || p.types.includes(type));
}

/** Tests only. */
export function clearEditorPanels() {
  panels.clear();
}
