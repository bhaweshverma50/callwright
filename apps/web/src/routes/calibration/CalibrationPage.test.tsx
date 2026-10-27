import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import type { CalibrationRow } from "../../api/quality";
import { env } from "../../lib/env";
import { server } from "../../mocks/node";
import { reading, wilson } from "../../mocks/quality/handlers";
import { renderApp, signInDemo } from "../../test/render";

const row = (over: Partial<CalibrationRow>): CalibrationRow => ({
  evaluator_id: "evl_builtin_intent_fulfillment",
  evaluator_name: "intent_fulfillment",
  display_name: "Intent fulfillment",
  scope: "call",
  cost_class: "llm_judge",
  evaluator_version: 2,
  version_scope: "current",
  both_pass: 4,
  both_fail: 2,
  over_eager: 2,
  missed: 2,
  n: 10,
  agreement_rate: 0.6,
  agreement_ci: { low: 0.313, high: 0.832 },
  under_min_sample: false,
  reading: "partial",
  current_threshold: null,
  best_threshold: null,
  best_threshold_agreement: null,
  ...over,
});

function serve(items: CalibrationRow[]) {
  server.use(
    http.get(`${env.apiBaseUrl}/calibration/evaluators`, () => HttpResponse.json({ min_sample_for_signal: 5, items })),
    http.get(`${env.apiBaseUrl}/calibration/summary`, () =>
      HttpResponse.json({ annotated_calls: 14, annotated_and_evaluated_calls: 10, conflicting_label_calls: 1, min_sample_for_signal: 5 }),
    ),
  );
}

describe("calibration math in the mock API (R7)", () => {
  it("matches the reference Wilson range for 6 of 10", () => {
    const ci = wilson(6, 10)!;
    expect(ci.low).toBeCloseTo(0.313, 3);
    expect(ci.high).toBeCloseTo(0.832, 3);
  });
  it("reads the bands at their boundaries", () => {
    expect(reading({ both_pass: 2, both_fail: 2, over_eager: 0, missed: 0, n: 4 })).toBe("insufficient");
    expect(reading({ both_pass: 4, both_fail: 2, over_eager: 2, missed: 2, n: 10 })).toBe("partial");
    expect(reading({ both_pass: 6, both_fail: 0, over_eager: 4, missed: 0, n: 10 })).toBe("over_eager");
    expect(reading({ both_pass: 17, both_fail: 0, over_eager: 3, missed: 0, n: 20 })).toBe("strong");
    expect(reading({ both_pass: 5, both_fail: 0, over_eager: 3, missed: 2, n: 10 })).toBe("partial");
  });
});

describe("CalibrationPage (007 T054, US4)", () => {
  it("shows the 2x2 matrix, 60% agreement and the partial reading", async () => {
    serve([row({})]);
    await signInDemo();
    renderApp("/calibration");
    const card = await screen.findByRole("listitem", { name: "Intent fulfillment" }, { timeout: 5000 });
    const matrix = within(card).getByRole("table", { name: "Intent fulfillment agreement matrix" });
    expect(within(matrix).getByText("Both pass").previousSibling).toHaveTextContent("4");
    expect(within(matrix).getByText("Both fail").previousSibling).toHaveTextContent("2");
    expect(within(matrix).getByText("Over-eager").previousSibling).toHaveTextContent("2");
    expect(within(matrix).getByText("Missed").previousSibling).toHaveTextContent("2");
    expect(within(card).getByText("60%")).toBeInTheDocument();
    expect(within(card).getByText("Partial agreement")).toBeInTheDocument();
    expect(within(card).getByText("95% range 31% to 83%")).toBeInTheDocument();
    expect(screen.getByText("Conflicting labels").parentElement).toHaveTextContent("1");
  });

  it("greys out a check under the minimum sample", async () => {
    serve([row({ n: 4, both_pass: 2, both_fail: 2, over_eager: 0, missed: 0, under_min_sample: true, reading: "insufficient", agreement_rate: 1 })]);
    await signInDemo();
    renderApp("/calibration");
    expect(await screen.findByText("Not enough data (4 of 5)", undefined, { timeout: 5000 })).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("says which way to move the threshold for an over-eager threshold check", async () => {
    serve([
      row({
        evaluator_id: "evl_builtin_anomaly_detection",
        evaluator_name: "anomaly_detection",
        display_name: "Anomaly detection",
        cost_class: "free",
        both_pass: 6,
        both_fail: 0,
        over_eager: 4,
        missed: 0,
        reading: "over_eager",
        current_threshold: 0.7,
        best_threshold: 0.85,
        best_threshold_agreement: 0.9,
      }),
    ]);
    await signInDemo();
    renderApp("/calibration");
    expect(await screen.findByText(/It flags calls you consider fine/, undefined, { timeout: 5000 })).toBeInTheDocument();
    expect(screen.getByText("Raise the threshold from 0.7 to 0.85: agreement would be 90% on the same calls.")).toBeInTheDocument();
  });

  it("switches the version scope in the address", async () => {
    const user = userEvent.setup();
    serve([row({})]);
    await signInDemo();
    const { router } = renderApp("/calibration");
    await user.click(await screen.findByRole("radio", { name: "All versions" }, { timeout: 5000 }));
    expect(router.state.location.search).toContain("versions=all");
  });
});
