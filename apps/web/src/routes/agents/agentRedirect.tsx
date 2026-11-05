import { FlowArrow, PhoneCall } from "@phosphor-icons/react";
import { ChevronLeft, Clock3, MessageSquareText } from "lucide-react";
import type { ReactNode } from "react";
import { Link, Navigate, useParams } from "react-router";
import { useAgent } from "../../api/agents";
import { isApiError } from "../../api/errors";
import { problemMessage } from "../../api/problems";
import { Badge, Button, EmptyState, PanelLoader } from "../../components";
import { RecordNotFound } from "../NotFound";

const ULID = /^agt_[0-9A-HJKMNP-TV-Z]{26}$/;

/** `/agents/:id` opens the right builder for the agent's type (T024). */
export function AgentRedirect() {
  const { id = "" } = useParams();
  const valid = ULID.test(id);
  const agent = useAgent(valid ? id : undefined);
  if (!valid || (isApiError(agent.error) && agent.error.status === 404))
    return <RecordNotFound kind="agent" backTo="/agents" backLabel="Back to Agents" />;
  if (agent.error)
    return (
      <EmptyState icon={<PhoneCall weight="duotone" />} title="The agent did not load">
        {problemMessage(agent.error, "agent")}
      </EmptyState>
    );
  if (!agent.data) return <PanelLoader label="Opening agent" />;
  return <Navigate replace to={`/agents/${id}/${agent.data.type === "flow" ? "flow" : "edit"}`} />;
}

function Later({
  back,
  backLabel,
  icon,
  title,
  children,
  actions,
}: {
  back: string;
  backLabel: string;
  icon: ReactNode;
  title: string;
  children: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <>
      <Link to={back} className="link-underline mb-4 inline-flex w-fit items-center gap-1 rounded-inline text-[13px] text-fg-2 hover:text-fg">
        <ChevronLeft className="size-4" aria-hidden /> {backLabel}
      </Link>
      <section className="relative overflow-hidden rounded-feature border border-line bg-surface shadow-2">
        <div className="relative flex flex-col gap-1 px-6 pt-6 sm:px-10">
          <Badge icon={<Clock3 />} className="w-fit">
            In a later release
          </Badge>
        </div>
        <EmptyState className="relative px-6 pb-10 pt-4 sm:px-10" icon={icon} title={title} actions={actions}>
          {children}
        </EmptyState>
      </section>
    </>
  );
}

/** `/agents/new/flow` and `/agents/:id/flow`: the flow builder ships with spec 004. */
export function FlowBuilderPlaceholder() {
  const { id } = useParams();
  return (
    <Later
      back={id ? "/agents" : "/agents/new"}
      backLabel={id ? "Agents" : "Agent type"}
      icon={<FlowArrow weight="duotone" />}
      title={id ? "The flow builder is on its way" : "Flow agents arrive with the flow builder"}
      actions={
        <Button asChild variant="primary" icon={<MessageSquareText aria-hidden />}>
          <Link to="/agents/templates">Start a single-prompt agent</Link>
        </Button>
      }
    >
      Flow agents are drawn as a canvas of steps with branches and per-step prompts. Until the builder is released, single-prompt agents cover most
      call flows: their prompt can describe each step and tools handle transfers.
    </Later>
  );
}
