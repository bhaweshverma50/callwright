const LABELS = ["Details", "Actions", "Outcome", "Next step"] as const;

/** A call summary: the first line as a sentence, then any "Details:", "Actions:", "Outcome:" and
 * "Next step:" lines as a two-column list. Older one-paragraph summaries render as they are. */
export function SummaryText({ text }: { text: string }) {
  const lines = text.split("\n").filter((l) => l.trim());
  const rows: { label: string; value: string }[] = [];
  const prose: string[] = [];
  for (const line of lines) {
    const label = LABELS.find((l) => line.startsWith(`${l}:`));
    if (label) rows.push({ label, value: line.slice(label.length + 1).trim() });
    else prose.push(line);
  }
  return (
    <div className="flex flex-col gap-3">
      {prose.map((p, i) => (
        <p key={i} className="max-w-[72ch] text-[13.5px] leading-relaxed text-fg">
          {p}
        </p>
      ))}
      {rows.length > 0 && (
        <dl className="grid grid-cols-[minmax(0,1fr)] gap-x-4 gap-y-2 text-[13px] sm:grid-cols-[96px_minmax(0,1fr)]">
          {rows.map((r) => (
            <div key={r.label} className="contents">
              <dt className="text-fg-3">{r.label}</dt>
              <dd className="leading-relaxed text-fg-2">{r.value}</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}
