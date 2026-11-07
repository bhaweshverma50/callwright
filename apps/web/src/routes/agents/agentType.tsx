import { MessageSquareText, Workflow, type LucideIcon } from "lucide-react";
import type { AgentType } from "../../api/agents";
import { Badge } from "../../components";

/** How each agent type is named and drawn wherever agents are listed or created. */
export const AGENT_TYPES: Record<AgentType, { label: string; icon: LucideIcon }> = {
  single_prompt: { label: "Single prompt", icon: MessageSquareText },
  flow: { label: "Flow", icon: Workflow },
};

export function AgentTypeBadge({ type }: { type: AgentType }) {
  const { label, icon: Icon } = AGENT_TYPES[type];
  return <Badge icon={<Icon />}>{label}</Badge>;
}
