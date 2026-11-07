/**
 * Pre-flight step (US2, T056, FR-015): before any simulation starts, show how many runs will
 * start, the estimated cost, tools without a mock response (with "Configure mocks" or run anyway)
 * and calls that will be skipped. Shown inside the start dialogs as their second step.
 */
import { Info, TriangleAlert, Wrench } from "lucide-react";
import { Link } from "react-router";
import type { AgentType } from "../../api/agents";
import type { Preflight } from "../../api/simulations";
import { Button, Figure } from "../../components";
import { agentEditPath, agentFlowPath } from "../../lib/paths";
import { costUsd, plural } from "../../lib/format";
import { INVALID_REASONS } from "./invalidCalls";

export function configureMocksPath(agentId: string, type: AgentType | undefined) {
  return type === "flow" ? agentFlowPath(agentId) : `${agentEditPath(agentId)}?tab=tools`;
}

export function PreflightStep({ report, agentId, agentType }: { report: Preflight; agentId: string; agentType: AgentType | undefined }) {
  const missing = report.tools_missing_mock;
  return (
    <div className="flex flex-col gap-4" aria-label="Pre-flight check" role="group">
      <div className="grid grid-cols-2 gap-4 rounded-control border border-line px-4 py-3">
        <Figure label="Runs to start">{report.run_count}</Figure>
        <Figure label="Estimated cost">{costUsd(report.estimated_cost_usd)}</Figure>
      </div>

      {missing.length > 0 && (
        <div className="flex flex-col gap-3 rounded-control border border-warning/40 bg-warning-soft px-3.5 py-3 text-warning-text" role="alert">
          <p className="flex items-start gap-2 text-[14px] font-medium">
            <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
            {missing.length === 1 ? "1 tool has no mock response" : `${missing.length} tools have no mock response`}
          </p>
          <ul className="flex flex-wrap gap-1.5 pl-6">
            {missing.map((t) => (
              <li
                key={`${t.kind}-${t.tool_id ?? t.node_id ?? t.name}`}
                className="inline-flex items-center gap-1.5 rounded-full bg-surface px-2.5 py-1 font-mono text-[12px] text-fg"
              >
                <Wrench className="size-3 text-fg-3" aria-hidden />
                {t.name}
                {t.kind === "webhook_node" && <span className="font-sans text-fg-3">webhook node</span>}
              </li>
            ))}
          </ul>
          <p className="pl-6 text-[13px] leading-relaxed text-fg-2">
            Simulations never call real systems. If you run anyway, these calls are answered by the output recorded in the original call when there is
            one, otherwise by a generated stand-in. Each answer is labelled with its source.
          </p>
          <Button asChild size="sm" variant="secondary" className="ml-6 w-fit">
            <Link to={configureMocksPath(agentId, agentType)}>Configure mocks</Link>
          </Button>
        </div>
      )}

      {report.invalid_calls.length > 0 && (
        <div className="flex flex-col gap-2">
          <p className="text-[13px] font-medium text-fg">{plural(report.invalid_calls.length, "call")} will be skipped</p>
          <ul className="max-h-40 divide-y divide-line overflow-y-auto rounded-control border border-line text-[13px]">
            {report.invalid_calls.map((c) => (
              <li key={c.call_id} className="flex flex-col gap-0.5 px-3 py-2 sm:flex-row sm:items-center sm:gap-3">
                <span className="min-w-0 truncate font-mono text-fg-2">{c.call_id}</span>
                <span className="text-fg-3 sm:ml-auto sm:shrink-0">{INVALID_REASONS[c.reason]}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {report.warnings.map((w) => (
        <p key={w} className="flex items-start gap-2 text-[13px] text-fg-2">
          <Info className="mt-0.5 size-3.5 shrink-0 text-fg-3" aria-hidden />
          {w}
        </p>
      ))}
    </div>
  );
}
