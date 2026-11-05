import { ArrowsLeftRight, PhoneX } from "@phosphor-icons/react";
import { ArrowLeft, ArrowLeftRight, GitCompareArrows, ShieldCheck } from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import {
  useCall,
  useCalls,
  useCompare,
  useTranscript,
  useTurnLatencies,
  type CallComparison,
  type CallDetail,
  type TranscriptItem,
  type TurnLatency,
} from "../../api/calls";
import { problemMessage } from "../../api/problems";
import { Badge, Button, EmptyState, Input, PageHeader, Panel, Skeleton, TruncatedText, cn, focusRing } from "../../components";
import { StatusBadge } from "./CallDetailDrawer";
import { mss, usd, when } from "./format";
import { transcriptRows, TurnLatencyChip } from "./Transcript";

function SideCard({ call, side, kind }: { call: CallDetail; side: "left" | "right"; kind: "call" | "simulation" }) {
  return (
    <div className="lift flex min-w-0 flex-col gap-3 rounded-panel border border-line bg-surface p-4 shadow-1">
      <div className="flex items-center justify-between gap-2">
        <Badge tone={side === "left" ? "neutral" : "accent"}>
          {side === "left" ? "Original" : kind === "simulation" ? "Simulated" : "Compared with"}
        </Badge>
        <StatusBadge status={call.status} />
      </div>
      <div className="min-w-0">
        <p className="flex min-w-0 items-center gap-1.5 text-[14px] font-medium text-fg">
          <TruncatedText>{call.agent.name}</TruncatedText>
          {call.agent_version_label && <Badge tone="accent">{call.agent_version_label}</Badge>}
        </p>
        <Link
          to={`/calls?call=${call.call_id}`}
          className={cn("block truncate rounded-inline font-mono text-[12px] text-accent-text hover:underline", focusRing)}
        >
          {call.call_id}
        </Link>
      </div>
      <dl className="grid grid-cols-3 gap-2 text-[12px]">
        <div>
          <dt className="text-fg-3">Duration</dt>
          <dd className="font-mono text-[13px] text-fg tnum">{mss(call.duration_s)}</dd>
        </div>
        <div>
          <dt className="text-fg-3">Cost</dt>
          <dd className="font-mono text-[13px] text-fg tnum">{usd(call.cost_usd ?? null)}</dd>
        </div>
        <div>
          <dt className="text-fg-3">Avg turn</dt>
          <dd className="font-mono text-[13px] text-fg tnum">{call.latency.avg_ms != null ? `${call.latency.avg_ms} ms` : "n/a"}</dd>
        </div>
      </dl>
      <p className="text-[12px] text-fg-3">{when(call.started_at)}</p>
    </div>
  );
}

function Items({ ids, items, latencies }: { ids: string[]; items: Map<string, TranscriptItem>; latencies: Map<number, TurnLatency> }) {
  const list = ids.map((id) => items.get(id)).filter((i): i is TranscriptItem => Boolean(i));
  if (!list.length) return <p className="text-[13px] italic text-fg-3">No turn</p>;
  return (
    <div className="flex flex-col gap-2">
      {transcriptRows(list).map((r) => {
        if (r.kind === "message") {
          const agent = r.item.role === "agent";
          const lat = agent && r.item.turn_index != null ? latencies.get(r.item.turn_index) : undefined;
          return (
            <div key={r.item.id} className={cn("rounded-control px-3 py-2", agent ? "bg-accent-soft/40" : "bg-surface-2/70")}>
              <p className="mb-0.5 flex flex-wrap items-center gap-2 text-[12px] font-medium text-fg-2">
                {agent ? "Agent" : "Caller"}
                {lat && <TurnLatencyChip turn={lat} />}
                {r.item.interrupted && <Badge tone="warning">Interrupted</Badge>}
              </p>
              <p className="text-[13px] leading-relaxed text-fg">{r.item.text}</p>
            </div>
          );
        }
        const result = r.kind === "tool" ? r.result : r.item;
        const name = r.item.tool_name;
        return (
          <p key={r.item.id} className="flex items-center gap-2 rounded-control border border-line px-3 py-1.5 text-[12px] text-fg-2">
            <span className="font-mono">{name}</span>
            {result?.is_error ? <Badge tone="danger">Error</Badge> : result ? <Badge tone="success">Done</Badge> : null}
          </p>
        );
      })}
    </div>
  );
}

function Picker({ callId }: { callId: string }) {
  const navigate = useNavigate();
  const call = useCall(callId);
  const [other, setOther] = useState("");
  const recent = useMemo(() => {
    const q = new URLSearchParams({ page: "1", page_size: "8", origin: "live,test,simulation" });
    if (call.data) q.set("agent_id", call.data.agent.id);
    return q;
  }, [call.data]);
  const list = useCalls(recent);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const v = other.trim();
    if (v.startsWith("srun_")) navigate(`?sim=${encodeURIComponent(v)}`);
    else if (v) navigate(`?with=${encodeURIComponent(v)}`);
  };
  const options = (list.data?.items ?? []).filter((c) => c.call_id !== callId);
  return (
    <Panel
      title="Pick a call to compare with"
      description="Paste a call ID or a simulation run ID, or pick a recent call of the same agent."
      icon={<ArrowLeftRight />}
    >
      <form onSubmit={submit} className="flex flex-wrap gap-2">
        <Input
          className="min-w-0 flex-1"
          aria-label="Call or simulation run ID"
          placeholder="call_... or srun_..."
          value={other}
          onChange={(e) => setOther(e.target.value)}
        />
        <Button type="submit" variant="primary" icon={<GitCompareArrows aria-hidden />} disabled={!other.trim()}>
          Compare
        </Button>
      </form>
      <ul className="mt-4 flex flex-col divide-y divide-line rounded-control border border-line">
        {!list.data
          ? Array.from({ length: 4 }, (_, i) => (
              <li key={i} className="px-3 py-3">
                <Skeleton className="h-3.5 w-2/3" />
              </li>
            ))
          : options.map((c) => (
              <li key={c.call_id}>
                <Link
                  to={`?with=${c.call_id}`}
                  className={cn("flex items-center gap-3 px-3 py-2.5 text-[13px] transition-colors hover:bg-accent-soft/40", focusRing)}
                >
                  <span className="min-w-0 flex-1 truncate font-mono text-[12px] text-fg-2">{c.call_id}</span>
                  {c.origin === "simulation" && <Badge tone="accent">Simulated</Badge>}
                  <span className="hidden text-fg-3 sm:inline">{when(c.started_at)}</span>
                  <span className="font-mono text-fg-2 tnum">{mss(c.duration_s)}</span>
                </Link>
              </li>
            ))}
        {list.data && options.length === 0 && <li className="px-3 py-3 text-[13px] text-fg-3">No other calls for this agent yet.</li>}
      </ul>
    </Panel>
  );
}

function Comparison({ data }: { data: CallComparison }) {
  const left = useTranscript(data.left.call_id);
  const right = useTranscript(data.right.call_id);
  const lLat = useTurnLatencies(data.left.call_id);
  const rLat = useTurnLatencies(data.right.call_id);
  const lItems = new Map((left.data?.items ?? []).map((i) => [i.id, i as TranscriptItem]));
  const rItems = new Map((right.data?.items ?? []).map((i) => [i.id, i as TranscriptItem]));
  const lTurns = new Map((lLat.data?.turns ?? []).map((t) => [t.turn_index, t]));
  const rTurns = new Map((rLat.data?.turns ?? []).map((t) => [t.turn_index, t]));
  const differing = data.flow_diff.filter((f) => f.differs).length;
  return (
    <div className="flex flex-col gap-6">
      <div className="grid grid-cols-[minmax(0,1fr)] gap-4 md:grid-cols-2">
        <SideCard call={data.left} side="left" kind="call" />
        <SideCard call={data.right} side="right" kind={data.right_kind} />
      </div>

      <Panel title="Transcripts by turn" description="Turn N of one call lines up with turn N of the other." bodyClassName="p-0">
        {!left.data || !right.data ? (
          <div className="flex flex-col gap-3 p-5" aria-hidden>
            {Array.from({ length: 4 }, (_, i) => (
              <Skeleton key={i} className="h-16 w-full" />
            ))}
          </div>
        ) : data.alignment.length === 0 ? (
          <p className="px-5 py-6 text-[13px] text-fg-3">Neither call has a transcript.</p>
        ) : (
          <ol className="divide-y divide-line">
            {data.alignment.map((a) => (
              <li key={a.turn_index} className="grid grid-cols-[minmax(0,1fr)] gap-3 px-5 py-4 md:grid-cols-[56px_minmax(0,1fr)_minmax(0,1fr)]">
                <span className="font-mono text-[12px] text-fg-3 tnum">{a.turn_index === 0 ? "Start" : `Turn ${a.turn_index}`}</span>
                <Items ids={a.left_item_ids ?? []} items={lItems} latencies={lTurns} />
                <Items ids={a.right_item_ids ?? []} items={rItems} latencies={rTurns} />
              </li>
            ))}
          </ol>
        )}
      </Panel>

      <div className="grid grid-cols-[minmax(0,1fr)] gap-6 lg:grid-cols-2">
        <Panel
          title="Flow path"
          description={data.flow_diff.length ? `${differing} of ${data.flow_diff.length} steps differ` : "Single-prompt agents have no flow path."}
          bodyClassName="p-0"
        >
          {data.flow_diff.length === 0 ? (
            <p className="px-5 py-5 text-[13px] text-fg-3">No flow transitions on either call.</p>
          ) : (
            <table className="w-full text-[13px]">
              <caption className="sr-only">Nodes visited, step by step</caption>
              <thead>
                <tr className="border-b border-line bg-surface-2/70 text-left text-[12px] text-fg-3">
                  <th scope="col" className="h-9 w-14 pl-5 font-medium">
                    Step
                  </th>
                  <th scope="col" className="font-medium">
                    Original
                  </th>
                  <th scope="col" className="pr-5 font-medium">
                    {data.right_kind === "simulation" ? "Simulated" : "Other"}
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.flow_diff.map((f) => (
                  <tr key={f.sequence} className={cn("border-b border-line last:border-0", f.differs && "bg-warning-soft/50")}>
                    <td className="h-10 pl-5 font-mono text-fg-3 tnum">{f.sequence}</td>
                    <td className={cn("font-mono text-[13px]", f.differs ? "text-warning-text" : "text-fg-2")}>{f.left_node_id ?? "n/a"}</td>
                    <td className={cn("pr-5 font-mono text-[13px]", f.differs ? "font-medium text-warning-text" : "text-fg-2")}>
                      {f.right_node_id ?? "n/a"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>
        <Panel title="Quality checks" description="Evaluator verdicts on each call and how the score moved." bodyClassName="p-0">
          {data.verdict_diffs.length === 0 ? (
            <div className="flex items-start gap-3 px-5 py-5">
              <ShieldCheck className="mt-0.5 size-4 shrink-0 text-fg-3" aria-hidden />
              <p className="text-[13px] text-fg-3">
                No evaluator has scored both calls yet. Turn on quality checks for this agent to compare verdicts.
              </p>
            </div>
          ) : (
            <table className="w-full text-[13px]">
              <caption className="sr-only">Verdict differences</caption>
              <thead>
                <tr className="border-b border-line bg-surface-2/70 text-left text-[12px] text-fg-3">
                  <th scope="col" className="h-9 pl-5 font-medium">
                    Evaluator
                  </th>
                  <th scope="col" className="font-medium">
                    Original
                  </th>
                  <th scope="col" className="font-medium">
                    Other
                  </th>
                  <th scope="col" className="pr-5 text-right font-medium">
                    Change
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.verdict_diffs.map((v) => (
                  <tr key={v.evaluator_id} className="border-b border-line last:border-0">
                    <td className="h-10 pl-5 text-fg">{v.evaluator_name}</td>
                    <td className="text-fg-2">{v.left?.verdict ?? "n/a"}</td>
                    <td className="text-fg-2" title={v.right_rationale ?? undefined}>
                      {v.right?.verdict ?? "n/a"}
                    </td>
                    <td className="pr-5 text-right font-mono tnum">
                      {v.score_delta == null ? "n/a" : v.score_delta > 0 ? `+${v.score_delta}` : v.score_delta}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>
      </div>
    </div>
  );
}

/** Two calls side by side (US4): headers, transcripts aligned by turn, flow paths and verdicts. */
export function ComparePage() {
  const { callId = "" } = useParams();
  const [params] = useSearchParams();
  const withCall = params.get("with");
  const sim = params.get("sim");
  const cmp = useCompare(callId, { withCall, sim });
  const picking = !withCall && !sim;
  return (
    <>
      <PageHeader
        title="Compare calls"
        description="Line two calls up turn by turn to see what a change did."
        actions={
          <Button asChild variant="secondary" icon={<ArrowLeft aria-hidden />}>
            <Link to={`/calls?call=${callId}`}>Back to the call</Link>
          </Button>
        }
      />
      {picking ? (
        <div className="max-w-[720px]">
          <Picker callId={callId} />
        </div>
      ) : cmp.isError ? (
        <EmptyState
          icon={<PhoneX weight="duotone" />}
          title="Call not found"
          actions={
            <Button asChild variant="secondary" icon={<ArrowsLeftRight aria-hidden />}>
              <Link to={`/calls/${callId}/compare`}>Pick another call</Link>
            </Button>
          }
        >
          {problemMessage(cmp.error, "call")}
        </EmptyState>
      ) : !cmp.data ? (
        <div className="flex flex-col gap-4" aria-busy="true">
          <div className="grid grid-cols-[minmax(0,1fr)] gap-4 md:grid-cols-2">
            <Skeleton className="h-[164px] rounded-panel" />
            <Skeleton className="h-[164px] rounded-panel" />
          </div>
          <Skeleton className="h-80 rounded-panel" />
        </div>
      ) : (
        <Comparison data={cmp.data} />
      )}
    </>
  );
}
