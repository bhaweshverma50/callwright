import { useQueryClient } from "@tanstack/react-query";
import { CircleDashed, Cpu, LoaderCircle, RotateCw } from "lucide-react";
import { useState } from "react";
import type { CallDetail } from "../../../api/calls";
import { callKeys } from "../../../api/calls";
import { isApiError } from "../../../api/errors";
import { problemMessage } from "../../../api/problems";
import { qualityKeys, rerunAnalysis, useCallAnalysis, type AnalysisValue } from "../../../api/quality";
import { Button, Skeleton, toast } from "../../../components";
import { AnalysisTable, SentimentBadge } from "../AnalysisTable";

function show(v: AnalysisValue): string {
  if (v.value === null || v.value === undefined || v.value === "") return "not found";
  if (typeof v.value === "boolean") return v.value ? "Yes" : "No";
  if (typeof v.value === "number") return v.value.toLocaleString("en-US");
  return String(v.value);
}

/**
 * Summary, sentiment and analysis values (US1) from the call's analysis record: values show
 * "not found" when the call did not contain them and "(renamed)" or "(deleted)" when the variable
 * changed since. Falls back to 006's table while the call is still processing.
 */
export function CallAnalysisPanel({ call }: { call: CallDetail }) {
  const qc = useQueryClient();
  const pending = call.processing_state === "pending";
  const analysis = useCallAnalysis(pending ? null : call.call_id);
  const [busy, setBusy] = useState(false);
  if (pending || analysis.isError) return <AnalysisTable call={call} />;
  if (analysis.isPending) {
    return (
      <div className="flex flex-col gap-3" aria-busy="true">
        <Skeleton className="h-14 w-full" />
        <Skeleton className="h-24 w-full" />
      </div>
    );
  }
  const a = analysis.data;
  const running = a.status === "pending" || a.status === "running";
  const rerun = async () => {
    setBusy(true);
    try {
      await rerunAnalysis(call.call_id);
      await qc.invalidateQueries({ queryKey: qualityKeys.analysis(call.call_id) });
      void qc.invalidateQueries({ queryKey: callKeys.detail(call.call_id) });
    } catch (e) {
      const detail =
        isApiError(e) && (e.status === 402 || e.status === 409) ? (e.problem.detail ?? problemMessage(e, "call")) : problemMessage(e, "call");
      toast({ tone: "error", title: "Could not re-run analysis", description: detail });
    } finally {
      setBusy(false);
    }
  };
  const values = a.values ?? [];
  return (
    <div className="flex flex-col gap-5">
      <section aria-labelledby="summary-h" className="flex flex-col gap-1.5">
        <div className="flex items-center justify-between gap-3">
          <h3 id="summary-h" className="text-[12.5px] text-fg-3">
            Summary
          </h3>
          {(a.status === "completed" || a.status === "skipped" || a.status === "error") &&
            (call.status === "completed" || call.status === "voicemail") && (
              <Button size="sm" variant="ghost" icon={<RotateCw aria-hidden />} pending={busy} onClick={() => void rerun()}>
                Re-run analysis
              </Button>
            )}
        </div>
        {running ? (
          <span role="status" className="inline-flex items-center gap-2 text-[13px] text-accent-text">
            <LoaderCircle className="size-4 animate-spin" aria-hidden /> Analysing the call
          </span>
        ) : a.status === "skipped" ? (
          <p className="text-[13px] text-fg-3">
            {a.skip_reason === "insufficient_credit"
              ? "Analysis skipped: insufficient credit. Re-run it after a top-up."
              : a.skip_reason === "too_short"
                ? "Not analysed: the call was too short to summarise. Re-run the analysis to force it."
                : "No analysis for this call: it never connected or had nothing to analyse."}
          </p>
        ) : a.status === "error" ? (
          <p className="text-[13px] text-danger-text">Analysis failed{a.error ? `: ${a.error}` : ""}. Try re-running it.</p>
        ) : (
          <p className="text-[13.5px] leading-relaxed text-fg">{a.summary ?? "No summary for this call."}</p>
        )}
      </section>
      <section aria-labelledby="sentiment-h" className="flex items-center justify-between gap-3">
        <h3 id="sentiment-h" className="text-[12.5px] text-fg-3">
          Sentiment
        </h3>
        {running ? <Skeleton className="h-5 w-20" /> : <SentimentBadge value={a.sentiment ?? (a.status === "completed" ? "unknown" : null)} />}
      </section>
      <section aria-labelledby="analysis-h" className="flex flex-col gap-2">
        <h3 id="analysis-h" className="text-[12.5px] text-fg-3">
          Analysis values
        </h3>
        {running ? (
          <Skeleton className="h-20 w-full" />
        ) : values.length === 0 ? (
          <p className="text-[13px] text-fg-3">No analysis variables are configured for this agent. Add them in the agent's Quality tab.</p>
        ) : (
          <table className="w-full overflow-hidden rounded-control border border-line text-[13px]">
            <caption className="sr-only">Analysis values</caption>
            <thead className="sr-only">
              <tr>
                <th scope="col">Field</th>
                <th scope="col">Value</th>
              </tr>
            </thead>
            <tbody>
              {values.map((v) => (
                <tr key={`${v.name}-${v.variable_id ?? ""}`} className="border-b border-line last:border-0 odd:bg-surface-2/40">
                  <th scope="row" className="w-2/5 px-3 py-2 text-left font-mono text-[12px] font-normal text-fg-2">
                    {v.name}
                    {v.status === "renamed" && <span className="ml-1.5 font-sans text-[11.5px] text-fg-3">(renamed)</span>}
                    {v.status === "deleted" && <span className="ml-1.5 font-sans text-[11.5px] text-fg-3">(deleted)</span>}
                  </th>
                  <td className="break-words px-3 py-2 text-fg">
                    {v.value === null || v.value === undefined || v.value === "" ? (
                      <span className="inline-flex items-center gap-1 text-fg-3">
                        <CircleDashed className="size-3.5" aria-hidden /> not found
                      </span>
                    ) : (
                      show(v)
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {a.model && (
          <p className="flex items-center gap-1.5 text-[11.5px] text-fg-3">
            <Cpu className="size-3" aria-hidden /> Extracted with <span className="font-mono">{a.model}</span>
          </p>
        )}
      </section>
    </div>
  );
}
