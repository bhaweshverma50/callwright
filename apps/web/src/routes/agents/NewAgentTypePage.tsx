import { ArrowRight, ArrowRightLeft, BookOpen, Braces, ChevronLeft, Copy, Cpu, GitBranch, Info, LayoutTemplate, PenLine, Wrench } from "lucide-react";
import { useReducedMotion } from "motion/react";
import { useId, useState, type ReactNode } from "react";
import { Link, useNavigate } from "react-router";
import { Badge, Button, ChoiceGroup, PageHeader, Textarea, cn } from "../../components";
import { DuplicateAgentDialog } from "./DuplicateAgentDialog";
import { AGENT_TYPES } from "./agentType";
import { AGENTS_PATH, NEW_FLOW_AGENT_PATH, NEW_SINGLE_AGENT_PATH, TEMPLATES_PATH } from "../../lib/paths";

type Kind = "single" | "flow";

const SingleIcon = AGENT_TYPES.single_prompt.icon;
const FlowIcon = AGENT_TYPES.flow.icon;

/**
 * New agent (T038, FR-001, US1.1). Leads with "describe it": a sentence or two opens a new single
 * prompt agent with the prompt assistant already drafting from it. Or start from a template or a
 * copy of an existing agent. Below, the type chooser: two cards that explain each type, single
 * prompt preselected, and a plain warning that the type cannot be changed later. Single prompt
 * continues to the templates; flow continues to the flow builder (spec 004).
 */
export function NewAgentTypePage() {
  const [kind, setKind] = useState<Kind>("single");
  const navigate = useNavigate();
  const labelId = useId();
  const describeId = useId();
  const [describe, setDescribe] = useState("");
  const [copying, setCopying] = useState(false);
  const draftWithAi = () => {
    const d = describe.trim();
    if (d) navigate(`${NEW_SINGLE_AGENT_PATH}?describe=${encodeURIComponent(d)}`);
  };
  return (
    <>
      <Link to={AGENTS_PATH} className="link-underline mb-4 inline-flex w-fit items-center gap-1 rounded-inline text-[13px] text-fg-2 hover:text-fg">
        <ChevronLeft className="size-4" aria-hidden /> Agents
      </Link>
      <PageHeader title="New agent" description="Describe what it should do and let the assistant draft it, or set it up yourself." />

      <section aria-labelledby={describeId} className="relative mb-8 overflow-hidden rounded-feature border border-line bg-surface shadow-2">
        <form
          className="relative flex flex-col gap-3 p-5 sm:p-6"
          onSubmit={(e) => {
            e.preventDefault();
            draftWithAi();
          }}
        >
          <div className="flex items-center gap-2.5">
            <span className="bg-accent grid size-8 place-items-center rounded-control text-white">
              <PenLine className="size-4" aria-hidden />
            </span>
            <h2 id={describeId} className="text-[15px] font-medium text-fg">
              What should this agent do?
            </h2>
            <Badge tone="accent">AI-drafted</Badge>
          </div>
          <Textarea
            aria-labelledby={describeId}
            rows={3}
            maxLength={2000}
            value={describe}
            onChange={(e) => setDescribe(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                draftWithAi();
              }
            }}
            placeholder="For example: answer calls for a dental clinic, book and move appointments, and transfer billing questions to the front desk."
            className="bg-surface text-[14px]"
          />
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-[13px] text-fg-3">
              Opens a single prompt agent with the assistant drafting the prompt and greeting. Nothing is saved until you save; about $0.02 per
              request.
            </p>
            <Button type="submit" variant="primary" icon={<ArrowRight aria-hidden />} disabled={!describe.trim()} className="shrink-0">
              Draft with AI
            </Button>
          </div>
          <div className="flex flex-wrap items-center gap-2 border-t border-line pt-3">
            <span className="mr-1 text-[13px] text-fg-3">Or start from</span>
            <Button asChild size="sm" icon={<LayoutTemplate aria-hidden />}>
              <Link to={TEMPLATES_PATH}>A template</Link>
            </Button>
            <Button size="sm" icon={<Copy aria-hidden />} onClick={() => setCopying(true)}>
              A copy of an existing agent
            </Button>
          </div>
        </form>
      </section>
      <DuplicateAgentDialog open={copying} onOpenChange={setCopying} agent={null} />

      <h2 id={labelId} className="mb-3 text-[13px] font-medium text-fg-2">
        Or choose the agent type yourself
      </h2>
      <ChoiceGroup
        aria-labelledby={labelId}
        size="lg"
        columns={2}
        value={kind}
        onValueChange={setKind}
        options={[
          {
            value: "single",
            title: AGENT_TYPES.single_prompt.label,
            icon: <SingleIcon aria-hidden />,
            description:
              "One system prompt runs the whole call. The model chooses the path turn by turn; best for open conversations and support lines.",
            children: (
              <>
                <TypeArt kind="single" on={kind === "single"} />
                <Bullets
                  items={[
                    { icon: <Braces />, text: "Free-form prompt with variables" },
                    { icon: <Wrench />, text: "Tools for lookups, transfers and ending calls" },
                    { icon: <BookOpen />, text: "Knowledge bases the agent can search" },
                  ]}
                />
              </>
            ),
          },
          {
            value: "flow",
            title: AGENT_TYPES.flow.label,
            icon: <FlowIcon aria-hidden />,
            meta: <Badge tone="accent">Builder in preview</Badge>,
            description:
              "A canvas of steps: greet, ask, branch, transfer. Best for scripted journeys, qualification and hand-offs you control step by step.",
            children: (
              <>
                <TypeArt kind="flow" on={kind === "flow"} />
                <Bullets
                  items={[
                    { icon: <GitBranch />, text: "Steps with conditions and branches" },
                    { icon: <ArrowRightLeft />, text: "Prompts, tools and captured values per step" },
                    { icon: <Cpu />, text: "A different model on each step if needed" },
                  ]}
                />
              </>
            ),
          },
        ]}
      />
      <div className="mt-6 flex flex-col gap-4 rounded-panel border border-line bg-surface-2/60 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
        <p className="flex items-start gap-2.5 text-[14px] text-fg-2">
          <Info className="mt-0.5 size-4 shrink-0 text-accent-text" aria-hidden />
          <span>
            <span className="font-medium text-fg">The type cannot be changed later.</span> To switch, create a new agent of the other type.
          </span>
        </p>
        <Button variant="primary" size="lg" className="shrink-0" onClick={() => navigate(kind === "single" ? TEMPLATES_PATH : NEW_FLOW_AGENT_PATH)}>
          Continue with {kind === "single" ? "single prompt" : "flow"}
        </Button>
      </div>
    </>
  );
}

function Bullets({ items }: { items: { icon: ReactNode; text: string }[] }) {
  return (
    <ul className="mt-1 flex flex-col gap-2">
      {items.map((b) => (
        <li key={b.text} className="flex items-center gap-2.5 text-[13px] text-fg-2">
          <span className="grid size-6 shrink-0 place-items-center rounded-full bg-surface-2 text-fg-3 [&_svg]:size-3.5">{b.icon}</span>
          {b.text}
        </li>
      ))}
    </ul>
  );
}

/**
 * A small diagram of each type. Single prompt: one prompt card driving a single model node that
 * loops back to the caller. Flow: a branching graph of steps. Connectors flow while the card is
 * selected (static under reduced motion).
 */
function TypeArt({ kind, on }: { kind: Kind; on: boolean }) {
  const reduce = useReducedMotion();
  const id = useId().replace(/:/g, "");
  const dash = on && !reduce ? "animate-flow" : undefined;
  const stroke = `url(#g-${id})`;
  const node = (x: number, y: number, w: number, label?: string, active?: boolean) => (
    <g>
      <rect
        x={x}
        y={y}
        width={w}
        height={26}
        rx={8}
        className={cn(
          "transition-colors duration-300",
          active && on ? "fill-[var(--accent-soft)] stroke-[var(--accent)]" : "fill-[var(--surface)] stroke-[var(--border-strong)]",
        )}
        strokeWidth={1.25}
      />
      {label && (
        <text x={x + w / 2} y={y + 17} textAnchor="middle" className="fill-[var(--text-2)] font-sans text-[11px]">
          {label}
        </text>
      )}
    </g>
  );
  return (
    <div
      className={cn("my-2 overflow-hidden rounded-control border border-line bg-surface-2/60 transition-colors duration-300", on && "bg-surface/70")}
    >
      <svg viewBox="0 0 320 112" className="block h-[112px] w-full" aria-hidden>
        <defs>
          <linearGradient id={`g-${id}`} x1="0" x2="320" y1="0" y2="0" gradientUnits="userSpaceOnUse">
            <stop offset="0" stopColor="var(--accent)" />
            <stop offset="1" stopColor="var(--accent)" />
          </linearGradient>
        </defs>
        {kind === "single" ? (
          <>
            <rect x={20} y={22} width={92} height={68} rx={10} className="fill-[var(--surface)] stroke-[var(--border-strong)]" strokeWidth={1.25} />
            {[36, 48, 60, 72].map((y, i) => (
              <rect key={y} x={32} y={y} width={i === 3 ? 40 : 68} height={5} rx={2.5} className="fill-[var(--surface-3)]" />
            ))}
            <path d="M112 56 H168" fill="none" stroke={on ? stroke : "var(--border-strong)"} strokeWidth={2} strokeDasharray="6 6" className={dash} />
            {node(168, 43, 64, "Model", true)}
            <path d="M232 56 H268" fill="none" stroke={on ? stroke : "var(--border-strong)"} strokeWidth={2} strokeDasharray="6 6" className={dash} />
            <circle
              cx={284}
              cy={56}
              r={14}
              className={cn("transition-colors duration-300", on ? "fill-[var(--accent)]" : "fill-[var(--surface-3)]")}
            />
            <path d="M279 51 l10 5 l-10 5 z" className={on ? "fill-white" : "fill-[var(--text-3)]"} />
          </>
        ) : (
          <>
            {node(14, 43, 58, "Greet", true)}
            <path
              d="M72 56 C 96 56, 96 26, 120 26"
              fill="none"
              stroke={on ? stroke : "var(--border-strong)"}
              strokeWidth={2}
              strokeDasharray="6 6"
              className={dash}
            />
            <path
              d="M72 56 C 96 56, 96 86, 120 86"
              fill="none"
              stroke={on ? stroke : "var(--border-strong)"}
              strokeWidth={2}
              strokeDasharray="6 6"
              className={dash}
            />
            {node(120, 13, 64, "Qualify", true)}
            {node(120, 73, 64, "Answer")}
            <path d="M184 26 H214" fill="none" stroke={on ? stroke : "var(--border-strong)"} strokeWidth={2} strokeDasharray="6 6" className={dash} />
            <path d="M184 86 H214" fill="none" stroke={on ? stroke : "var(--border-strong)"} strokeWidth={2} strokeDasharray="6 6" className={dash} />
            {node(214, 13, 64, "Book")}
            {node(214, 73, 64, "Transfer")}
            <path d="M278 26 C 298 26, 298 56, 306 56" fill="none" stroke="var(--border-strong)" strokeWidth={1.5} />
            <path d="M278 86 C 298 86, 298 56, 306 56" fill="none" stroke="var(--border-strong)" strokeWidth={1.5} />
          </>
        )}
      </svg>
    </div>
  );
}
