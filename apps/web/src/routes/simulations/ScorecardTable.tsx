/**
 * Scorecard table (US3, T067, FR-021): per check, the pass rate on the baseline and on the
 * simulated calls with sample sizes, the change in percentage points, and how many pairs improved,
 * regressed or stayed the same. Flow agents get the same figures per node. Wide tables scroll
 * inside their container.
 */
import type { ScorecardRow } from "../../api/simulations";
import { Table, Tooltip, cn, type Column } from "../../components";
import { deltaTone, pct, pp } from "./shared";

function Rate({ rate, passes, n }: { rate: number | null | undefined; passes: number; n: number }) {
  return (
    <span className="flex flex-col items-end whitespace-nowrap leading-tight">
      <span className="font-mono text-[13px] text-fg tnum">{pct(rate)}</span>
      <span className="font-mono text-[12px] text-fg-3 tnum">{n ? `${passes} of ${n}` : "no samples"}</span>
    </span>
  );
}

const score = (v: number | null | undefined) => (v === null || v === undefined ? "n/a" : v.toFixed(1));

export function scorecardColumns(rows: ScorecardRow[], opts: { byNode?: boolean; baselineLabel: string }): Column<ScorecardRow>[] {
  const hasScores = rows.some((r) => r.base_mean_score != null || r.sim_mean_score != null);
  return [
    ...(opts.byNode
      ? [
          {
            key: "node",
            header: "Node",
            cell: (r: ScorecardRow) => <span className="whitespace-nowrap font-medium text-fg">{r.node_label ?? r.node_id ?? "n/a"}</span>,
          },
        ]
      : []),
    {
      key: "check",
      header: "Check",
      cell: (r) => (
        <span className="flex items-baseline gap-1.5 whitespace-nowrap">
          <span className={cn(opts.byNode ? "text-fg-2" : "font-medium text-fg")}>{r.evaluator_display_name}</span>
          <span className="font-mono text-[11px] text-fg-3">v{r.evaluator_version}</span>
        </span>
      ),
    },
    { key: "base", header: opts.baselineLabel, align: "right", cell: (r) => <Rate rate={r.base_pass_rate} passes={r.base_passes} n={r.base_n} /> },
    { key: "sim", header: "Simulated", align: "right", cell: (r) => <Rate rate={r.sim_pass_rate} passes={r.sim_passes} n={r.sim_n} /> },
    {
      key: "delta",
      header: "Change",
      align: "right",
      cell: (r) => <span className={cn("whitespace-nowrap font-mono text-[13px] font-semibold tnum", deltaTone(r.delta_pp))}>{pp(r.delta_pp)}</span>,
    },
    {
      key: "improved",
      header: "Improved",
      numeric: true,
      cell: (r) => <span className={r.pairs.improved ? "text-success-text" : "text-fg-3"}>{r.pairs.improved}</span>,
    },
    {
      key: "regressed",
      header: "Regressed",
      numeric: true,
      cell: (r) => <span className={r.pairs.regressed ? "text-danger-text" : "text-fg-3"}>{r.pairs.regressed}</span>,
    },
    {
      key: "unchanged",
      header: "Unchanged",
      numeric: true,
      cell: (r) => {
        const value = <span className="text-fg-2">{r.pairs.unchanged_pass + r.pairs.unchanged_fail}</span>;
        return r.pairs.version_mismatch ? (
          <Tooltip
            content={`${r.pairs.version_mismatch} ${r.pairs.version_mismatch === 1 ? "pair was" : "pairs were"} left out: the check's version differed between the two calls.`}
          >
            <span tabIndex={0} className="cursor-help underline decoration-dotted underline-offset-2">
              {value}
            </span>
          </Tooltip>
        ) : (
          value
        );
      },
    },
    ...(hasScores
      ? [
          {
            key: "score",
            header: "Mean score",
            align: "right" as const,
            cell: (r: ScorecardRow) => (
              <span className="whitespace-nowrap font-mono text-[13px] text-fg-2 tnum">
                {r.base_mean_score == null && r.sim_mean_score == null ? "n/a" : `${score(r.base_mean_score)} to ${score(r.sim_mean_score)}`}
              </span>
            ),
          },
        ]
      : []),
  ];
}

export function ScorecardTable({
  rows,
  byNode = false,
  baselineLabel = "Original",
  caption,
}: {
  rows: ScorecardRow[];
  byNode?: boolean;
  baselineLabel?: string;
  caption: string;
}) {
  const sorted = byNode
    ? rows
        .slice()
        .sort((a, b) => (a.node_label ?? "").localeCompare(b.node_label ?? "") || a.evaluator_display_name.localeCompare(b.evaluator_display_name))
    : rows;
  return (
    <Table
      caption={caption}
      columns={scorecardColumns(rows, { byNode, baselineLabel })}
      rows={sorted}
      rowKey={(r) => `${r.evaluator_id}-${r.node_id ?? "call"}-${r.scope}`}
    />
  );
}
