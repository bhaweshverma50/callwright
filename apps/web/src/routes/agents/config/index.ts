/**
 * The agent configuration the flow builder shares with the single-prompt editor (004 FR-023,
 * FR-050 to FR-052): the draft, its catalogs, the editor's settings sections and extra tabs, the
 * field table and version history. The flow builder imports these from here, not from the editor's
 * files one by one.
 */
export { AdvancedSection } from "../editor/AdvancedSection";
export { CallBehaviorSection } from "../editor/CallBehaviorSection";
export type { Catalogs } from "../editor/catalogs";
export { ModelPicker } from "../editor/ModelPicker";
export { EDITOR_PANELS } from "../editor/panels";
export { TemperatureControl } from "../editor/TemperatureControl";
export { stable, useAgentDraft, type AgentDraft } from "../editor/useAgentDraft";
export { VoiceSection } from "../editor/VoiceSection";
export { VersionDrawer } from "../versions/VersionDrawer";
export { sectionKeys } from "./fields";
