import { BrainCircuit, Copy, Globe, MessageSquareText, Mic2, Radio, Trash2, TriangleAlert, Workflow } from "lucide-react";
import { motion } from "motion/react";
import { Link, useNavigate } from "react-router";
import type { AgentSummary } from "../../api/agents";
import { Badge, IconButton, Tooltip, TruncatedText, cn } from "../../components";

export function relativeDate(iso: string): string {
  const d = Math.floor((Date.now() - Date.parse(iso)) / 86_400_000);
  if (d <= 0) {
    const h = Math.floor((Date.now() - Date.parse(iso)) / 3_600_000);
    return h <= 0 ? "just now" : `${h} h ago`;
  }
  if (d === 1) return "yesterday";
  if (d < 30) return `${d} days ago`;
  return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

/**
 * One agent in the list (T051, FR-018): name and type, what it runs (model, voice, language),
 * whether it is live and on which version, and when it last changed. The whole card opens the
 * agent; duplicate and delete sit above the link layer with their own focus and tooltips.
 */
export function AgentCard({
  agent,
  modelLabel,
  languageLabel,
  onDuplicate,
  onDelete,
  duplicating,
  fresh,
}: {
  agent: AgentSummary;
  modelLabel: string;
  languageLabel: string;
  onDuplicate: () => void;
  onDelete: () => void;
  duplicating: boolean;
  fresh?: boolean;
}) {
  const flow = agent.type === "flow";
  const TypeIcon = flow ? Workflow : MessageSquareText;
  const to = flow ? `/agents/${agent.id}/flow` : `/agents/${agent.id}/edit`;
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
          // The whole card opens the agent; its buttons, links and tips keep their own behaviour.
          if (!(e.target as HTMLElement).closest("a,button,[tabindex]")) navigate(to);
        }}
        className={cn(
          "group relative flex min-w-0 flex-1 cursor-pointer flex-col rounded-panel border bg-surface shadow-1 transition-[transform,box-shadow,border-color] duration-200",
          "hover:-translate-y-0.5 hover:border-accent/45 hover:shadow-glow focus-within:border-accent/45",
          fresh ? "border-accent/60 shadow-glow" : "border-line",
        )}
      >
        <div className="flex items-start gap-3 px-5 pb-3 pt-4">
          <span
            className={cn(
              "grid size-10 shrink-0 place-items-center rounded-control",
              flow ? "bg-warning-soft text-warning-text" : "bg-accent-soft text-accent-text",
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
            <TruncatedText className="font-mono text-[11.5px] text-fg-3">{agent.id}</TruncatedText>
          </div>
          <div className="-mr-2 -mt-1 flex shrink-0 items-center opacity-100 transition-opacity sm:opacity-60 sm:group-focus-within:opacity-100 sm:group-hover:opacity-100">
            <IconButton label={`Duplicate ${agent.name}`} className="size-8" pending={duplicating} onClick={onDuplicate}>
              <Copy className="size-4" aria-hidden />
            </IconButton>
            <IconButton label={`Delete ${agent.name}`} className="size-8 hover:bg-danger-soft hover:text-danger-text" onClick={onDelete}>
              <Trash2 className="size-4" aria-hidden />
            </IconButton>
          </div>
        </div>

        <dl className="mx-5 grid grid-cols-[minmax(0,1fr)] gap-y-2 border-y border-line py-3 text-[13px]">
          {[
            { icon: <BrainCircuit />, label: "Model", value: modelLabel },
            { icon: <Mic2 />, label: "Voice", value: agent.voice_label },
            { icon: <Globe />, label: "Language", value: languageLabel },
          ].map((r) => (
            <div key={r.label} className="flex min-w-0 items-center justify-between gap-4">
              <dt className="flex shrink-0 items-center gap-2 text-fg-3 [&_svg]:size-3.5">
                {r.icon}
                {r.label}
              </dt>
              <dd className="min-w-0 text-right text-fg">
                <TruncatedText>{r.value}</TruncatedText>
              </dd>
            </div>
          ))}
        </dl>

        <div className="flex flex-wrap items-center justify-between gap-2 px-5 py-3">
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge icon={<TypeIcon />}>{flow ? "Flow" : "Single prompt"}</Badge>
            {agent.published_version ? (
              <Badge tone="success" icon={<Radio />}>
                Live, version {agent.published_version.version_number}
              </Badge>
            ) : (
              <Badge>Not published</Badge>
            )}
            {agent.has_publish_blockers && (
              <Tooltip content="A component this agent uses has no price or was withdrawn. Open the agent to see what to replace.">
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
              {relativeDate(agent.updated_at)}
            </time>
          </span>
        </div>
      </article>
    </motion.div>
  );
}
