import { BrainCircuit, Captions, Globe, Mic2, Radio, TriangleAlert } from "lucide-react";
import { motion } from "motion/react";
import { Link, useNavigate } from "react-router";
import type { AgentSummary } from "../../api/agents";
import { Badge, Tooltip, TruncatedText, cn } from "../../components";
import { AgentActions } from "./AgentActions";
import { agentPath } from "../../lib/paths";
import { timeAgo } from "../../lib/format";
import { AGENT_TYPES, AgentTypeBadge } from "./agentType";

/** A value with the other choices a flow's nodes use: "GPT-5.1 +1", the rest in the tooltip. */
export function WithExtras({ value, extras }: { value: string; extras: string[] | undefined }) {
  if (!extras?.length) return <TruncatedText>{value}</TruncatedText>;
  return (
    <span className="flex min-w-0 items-baseline justify-end gap-1">
      <TruncatedText>{value}</TruncatedText>
      <span className="shrink-0 text-fg-3" title={`Also used by flow nodes: ${extras.join(", ")}`}>
        +{extras.length}
      </span>
    </span>
  );
}

/**
 * One agent in the list (T051, FR-018): name and type, what it runs (model, voice, language),
 * whether it is live and on which version, and when it last changed. The whole card opens the
 * agent; its actions menu sits above the link layer with its own focus.
 */
export function AgentCard({
  agent,
  modelLabel,
  modelExtras,
  languageLabel,
  onDuplicate,
  onDelete,
  fresh,
}: {
  agent: AgentSummary;
  modelLabel: string;
  modelExtras?: string[];
  languageLabel: string;
  onDuplicate: () => void;
  onDelete: () => void;
  fresh?: boolean;
}) {
  const TypeIcon = AGENT_TYPES[agent.type].icon;
  const to = agentPath(agent);
  const navigate = useNavigate();
  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.97 }}
      transition={{ duration: 0.24, ease: [0.16, 1, 0.3, 1] }}
      className="flex min-w-0"
    >
      <article
        onClick={(e) => {
          // The whole card opens the agent. Real controls keep their own behaviour; focusable text
          // (truncated labels with tips) does not count as one, and selecting text never navigates.
          if ((e.target as HTMLElement).closest("a,button,input,select,textarea,[role=menu],[role=menuitem]")) return;
          if (window.getSelection()?.toString()) return;
          navigate(to);
        }}
        className={cn(
          "group relative flex min-w-0 flex-1 cursor-pointer flex-col rounded-panel border bg-surface shadow-1 transition-[transform,box-shadow,border-color] duration-200",
          "hover:-translate-y-0.5 hover:border-accent/45 focus-within:border-accent/45",
          fresh ? "border-accent/60" : "border-line",
        )}
      >
        <div className="flex items-start gap-3 px-5 pb-3 pt-4">
          <span
            className={cn(
              "grid size-10 shrink-0 place-items-center rounded-control",
              agent.type === "flow" ? "bg-warning-soft text-warning-text" : "bg-accent-soft text-accent-text",
            )}
          >
            <TypeIcon className="size-5" aria-hidden />
          </span>
          <div className="flex min-w-0 flex-1 flex-col gap-0.5 pt-px">
            <h3 className="min-w-0 text-[15px] font-semibold leading-snug text-fg">
              <Link to={to} className="block rounded-inline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring">
                <TruncatedText focusable={false}>{agent.name}</TruncatedText>
              </Link>
            </h3>
            <TruncatedText className="font-mono text-[12px] text-fg-3">{agent.id}</TruncatedText>
          </div>
          <AgentActions agent={agent} onDuplicate={onDuplicate} onDelete={onDelete} className="-mr-2 -mt-1 shrink-0" />
        </div>

        <dl className="mx-5 grid grid-cols-[minmax(0,1fr)] gap-y-2 border-y border-line py-3 text-[13px]">
          {[
            { icon: <BrainCircuit />, label: "Model", value: modelLabel, extras: modelExtras },
            { icon: <Captions />, label: "Speech", value: agent.stt_label ?? "", extras: agent.stt_extra_labels },
            { icon: <Mic2 />, label: "Voice", value: agent.voice_label, extras: agent.voice_extra_labels },
            { icon: <Globe />, label: "Language", value: languageLabel, extras: undefined },
          ].map((r) => (
            <div key={r.label} className="flex min-w-0 items-center justify-between gap-4">
              <dt className="flex shrink-0 items-center gap-2 text-fg-3 [&_svg]:size-3.5">
                {r.icon}
                {r.label}
              </dt>
              <dd className="min-w-0 text-right text-fg">
                <WithExtras value={r.value} extras={r.extras} />
              </dd>
            </div>
          ))}
        </dl>

        <div className="flex flex-wrap items-center justify-between gap-2 px-5 py-3">
          <div className="flex flex-wrap items-center gap-1.5">
            <AgentTypeBadge type={agent.type} />
            {agent.published_version ? (
              <Badge tone="success" icon={<Radio />}>
                Live, version {agent.published_version.version_number}
              </Badge>
            ) : (
              <Badge>Not published</Badge>
            )}
            {(agent.has_publish_blockers || (agent.vendor_warnings?.length ?? 0) > 0) && (
              <Tooltip content={attentionReason(agent)}>
                <span tabIndex={0} className="rounded-full focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring">
                  <Badge tone="warning" icon={<TriangleAlert />}>
                    Needs attention
                  </Badge>
                </span>
              </Tooltip>
            )}
          </div>
          <span className="text-[12px] text-fg-3">
            <span className="sr-only">Updated </span>
            <time dateTime={agent.updated_at} title={new Date(agent.updated_at).toLocaleString()}>
              {timeAgo(agent.updated_at)}
            </time>
          </span>
        </div>
      </article>
    </motion.div>
  );
}

/** Why the card says Needs attention. */
export function attentionReason(agent: Pick<AgentSummary, "vendor_warnings" | "has_publish_blockers">): string {
  const vendors = agent.vendor_warnings ?? [];
  if (vendors.length) return `${vendors.join(" ")} Live calls on this agent are refused until you choose another provider.`;
  return "A component this agent uses has no price or was withdrawn. Open the agent to see what to replace.";
}
