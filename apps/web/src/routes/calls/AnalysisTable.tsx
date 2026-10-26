import { Frown, Meh, Smile, CircleHelp } from "lucide-react";
import type { CallDetail, Sentiment } from "../../api/calls";
import { Badge, Skeleton } from "../../components";
import { SENTIMENT_LABELS } from "./filters";
import { SENTIMENT_TONES } from "./format";

const SENTIMENT_ICONS = { positive: Smile, neutral: Meh, negative: Frown, unknown: CircleHelp } as const;

export function SentimentBadge({ value }: { value: Sentiment | null | undefined }) {
  if (!value) return <span className="text-fg-3">n/a</span>;
  const Icon = SENTIMENT_ICONS[value];
  return (
    <Badge tone={SENTIMENT_TONES[value]} icon={<Icon aria-hidden />}>
      {SENTIMENT_LABELS[value]}
    </Badge>
  );
}

function show(value: unknown): string {
  if (value === null || value === undefined || value === "") return "n/a";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function Processing() {
  return (
    <span className="inline-flex items-center gap-2 text-[12.5px] text-accent-text">
      <Skeleton className="h-3 w-16" />
      Processing
    </span>
  );
}

/** Summary, sentiment and analysis values as a field and value table (FR-014). */
export function AnalysisTable({ call }: { call: CallDetail }) {
  const pending = call.processing_state === "pending";
  const values = Object.entries(call.analysis_values ?? {});
  return (
    <div className="flex flex-col gap-5">
      <section aria-labelledby="summary-h" className="flex flex-col gap-1.5">
        <h3 id="summary-h" className="text-[12.5px] text-fg-3">
          Summary
        </h3>
        {pending ? <Processing /> : <p className="text-[13.5px] leading-relaxed text-fg">{call.summary ?? "No summary for this call."}</p>}
      </section>
      <section aria-labelledby="sentiment-h" className="flex items-center justify-between gap-3">
        <h3 id="sentiment-h" className="text-[12.5px] text-fg-3">
          Sentiment
        </h3>
        {pending ? <Processing /> : <SentimentBadge value={call.sentiment} />}
      </section>
      <section aria-labelledby="analysis-h" className="flex flex-col gap-2">
        <h3 id="analysis-h" className="text-[12.5px] text-fg-3">
          Analysis values
        </h3>
        {pending ? (
          <Processing />
        ) : values.length === 0 ? (
          <p className="text-[13px] text-fg-3">No analysis variables are configured for this agent.</p>
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
              {values.map(([k, v]) => (
                <tr key={k} className="border-b border-line last:border-0 odd:bg-surface-2/40">
                  <th scope="row" className="w-2/5 px-3 py-2 text-left font-mono text-[12px] font-normal text-fg-2">
                    {k}
                  </th>
                  <td className="break-words px-3 py-2 text-fg">{show(v)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
