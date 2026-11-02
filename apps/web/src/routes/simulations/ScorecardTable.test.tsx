import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ScorecardRow } from "../../api/simulations";
import { ScorecardTable } from "./ScorecardTable";
import { pct, pp } from "./shared";

const row = (patch: Partial<ScorecardRow>): ScorecardRow => ({
  evaluator_id: "evl_01INTENT",
  evaluator_name: "intent_fulfilled",
  evaluator_display_name: "Intent fulfilled",
  evaluator_version: 3,
  scope: "call",
  node_id: null,
  node_label: null,
  base_n: 10,
  base_passes: 4,
  base_pass_rate: 0.4,
  sim_n: 10,
  sim_passes: 7,
  sim_pass_rate: 0.7,
  delta_pp: 30,
  base_mean_score: null,
  sim_mean_score: null,
  pairs: { n: 10, improved: 3, regressed: 0, unchanged_pass: 4, unchanged_fail: 3, version_mismatch: 0 },
  ...patch,
});

describe("scorecard figures (FR-021, SC-003)", () => {
  it("formats rates and percentage points, rounding half away from zero", () => {
    expect(pct(0.4)).toBe("40%");
    expect(pct(null)).toBe("n/a");
    expect(pp(30)).toBe("+30.0 pp");
    expect(pp(-0.05)).toBe("-0.1 pp");
    expect(pp(0.04)).toBe("0.0 pp");
    expect(pp(null)).toBe("n/a");
  });

  it("shows the spec fixture as 40% vs 70%, +30.0 pp, 3 improved and 0 regressed", () => {
    render(<ScorecardTable rows={[row({})]} caption="Scorecard" />);
    const cells = within(screen.getAllByRole("row")[1]!).getAllByRole("cell");
    expect(cells.map((c) => c.textContent)).toEqual(["Intent fulfilledv3", "40%4 of 10", "70%7 of 10", "+30.0 pp", "3", "0", "7"]);
  });

  it("reads n/a with no samples, adds a node column and mean scores when present", () => {
    render(
      <ScorecardTable
        byNode
        caption="By node"
        rows={[
          row({ node_id: "confirm", node_label: "Confirm appointment", base_mean_score: 3.4, sim_mean_score: 4.1 }),
          row({
            node_id: "greet",
            node_label: "Greeting",
            base_n: 0,
            base_passes: 0,
            base_pass_rate: null,
            sim_n: 0,
            sim_passes: 0,
            sim_pass_rate: null,
            delta_pp: null,
          }),
        ]}
      />,
    );
    expect(screen.getAllByRole("columnheader").map((h) => h.textContent)).toEqual([
      "Node",
      "Check",
      "Original",
      "Simulated",
      "Change",
      "Improved",
      "Regressed",
      "Unchanged",
      "Mean score",
    ]);
    const greeting = within(screen.getAllByRole("row")[2]!).getAllByRole("cell");
    expect(greeting[2]).toHaveTextContent("n/ano samples");
    expect(greeting[4]).toHaveTextContent("n/a");
    expect(within(screen.getAllByRole("row")[1]!).getAllByRole("cell")[8]).toHaveTextContent("3.4 to 4.1");
  });
});
