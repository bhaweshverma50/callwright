import { Copy, History, MoreVertical, PencilLine, PhoneCall, Trash2 } from "lucide-react";
import { useNavigate } from "react-router";
import type { AgentSummary } from "../../api/agents";
import { Button, Menu, MenuContent, MenuItem, MenuSeparator, MenuTrigger, cn } from "../../components";

export const agentPath = (a: Pick<AgentSummary, "id" | "type">) => (a.type === "flow" ? `/agents/${a.id}/flow` : `/agents/${a.id}/edit`);

/** Everything you can do to one agent, always visible (not hover-only) on cards and table rows. */
export function AgentActions({
  agent,
  onDuplicate,
  onDelete,
  className,
}: {
  agent: AgentSummary;
  onDuplicate: () => void;
  onDelete: () => void;
  className?: string;
}) {
  const navigate = useNavigate();
  const open = agentPath(agent);
  return (
    <Menu>
      <MenuTrigger asChild>
        <Button variant="ghost" aria-label={`Actions for ${agent.name}`} className={cn("size-8 px-0", className)}>
          <MoreVertical className="size-4" aria-hidden />
        </Button>
      </MenuTrigger>
      <MenuContent>
        <MenuItem onSelect={() => navigate(open)}>
          <PencilLine aria-hidden /> {agent.type === "flow" ? "Open the canvas" : "Open in the editor"}
        </MenuItem>
        <MenuItem onSelect={() => navigate(`/agents/${agent.id}/testing`)}>
          <PhoneCall aria-hidden /> Test call
        </MenuItem>
        <MenuItem onSelect={() => navigate(`${open}?history=1`)}>
          <History aria-hidden /> Version history
        </MenuItem>
        <MenuItem onSelect={onDuplicate}>
          <Copy aria-hidden /> Duplicate…
        </MenuItem>
        <MenuSeparator />
        <MenuItem danger onSelect={onDelete}>
          <Trash2 aria-hidden /> Delete
        </MenuItem>
      </MenuContent>
    </Menu>
  );
}
