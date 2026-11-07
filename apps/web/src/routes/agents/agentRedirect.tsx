import { PhoneCall } from "@phosphor-icons/react";
import { Navigate, useParams } from "react-router";
import { useAgent } from "../../api/agents";
import { isApiError } from "../../api/errors";
import { problemMessage } from "../../api/problems";
import { EmptyState, PanelLoader } from "../../components";
import { RecordNotFound } from "../NotFound";
import { agentPath, AGENTS_PATH, isAgentId } from "../../lib/paths";

/** `/agents/:id` opens the right builder for the agent's type (T024). */
export function AgentRedirect() {
  const { id = "" } = useParams();
  const valid = isAgentId(id);
  const agent = useAgent(valid ? id : undefined);
  if (!valid || (isApiError(agent.error) && agent.error.status === 404))
    return <RecordNotFound kind="agent" backTo={AGENTS_PATH} backLabel="Back to Agents" />;
  if (agent.error)
    return (
      <EmptyState icon={<PhoneCall weight="duotone" />} title="The agent did not load">
        {problemMessage(agent.error, "agent")}
      </EmptyState>
    );
  if (!agent.data) return <PanelLoader label="Opening agent" />;
  return <Navigate replace to={agentPath(agent.data)} />;
}
