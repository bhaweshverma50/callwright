import { ArrowRight, CircleCheck, ListChecks, Zap, type LucideIcon } from "lucide-react";
import { withoutLineRefs } from "../../../lib/text";

const SECTIONS: { label: string; icon: LucideIcon; tone: string; list: boolean }[] = [
  { label: "Details", icon: ListChecks, tone: "bg-accent-soft text-accent-text", list: true },
  { label: "Actions", icon: Zap, tone: "bg-accent-soft text-accent-text", list: true },
  { label: "Outcome", icon: CircleCheck, tone: "bg-success-soft text-success-text", list: false },
  { label: "Next step", icon: ArrowRight, tone: "bg-warning-soft text-warning-text", list: false },
];
const INLINE_LABEL = /\s+(?=(?:Details|Actions|Outcome|Next step):)/g;

/** Same tidy-up the API applies to new summaries, for ones saved before it: drop transcript line
 * references like [3] or [6-8] and put each labelled part on its own line. */
export function tidySummary(text: string): string {
  return withoutLineRefs(text).replace(INLINE_LABEL, "\n");
}

const cap = (s: string) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);

/** The summary's first sentence, for one-line places such as the call list. */
export function summaryHeadline(text: string): string {
  return tidySummary(text).split("\n")[0]?.trim() ?? "";
}

/** The Outcome line of a structured summary, if it has one. */
export function summaryOutcome(text: string): string | null {
  const line = tidySummary(text)
    .split("\n")
    .find((l) => l.trim().startsWith("Outcome:"));
  return line ? cap(line.trim().slice("Outcome:".length).trim()) : null;
}

/** Facts in a Details or Actions line are separated by semicolons; one per bullet. */
const items = (value: string) =>
  value
    .split(/;\s*/)
    .map((s) => cap(s.trim().replace(/\.$/, "")))
    .filter(Boolean);

/** A call summary: the first line as a lead sentence, then Details and Actions as bullet lists and
 * Outcome and Next step as short lines, each with an icon and a bold label. Older one-paragraph
 * summaries render as a plain paragraph. */
export function SummaryText({ text }: { text: string }) {
  const lines = tidySummary(text)
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);
  const prose: string[] = [];
  const found: { section: (typeof SECTIONS)[number]; value: string }[] = [];
  for (const line of lines) {
    const section = SECTIONS.find((s) => line.startsWith(`${s.label}:`));
    if (section) found.push({ section, value: line.slice(section.label.length + 1).trim() });
    else prose.push(line);
  }
  return (
    <div className="flex flex-col gap-4">
      {prose.map((p, i) => (
        <p
          key={i}
          className={
            i === 0 && found.length
              ? "max-w-[72ch] text-[15px] font-medium leading-relaxed text-fg"
              : "max-w-[72ch] text-[14px] leading-relaxed text-fg"
          }
        >
          {p}
        </p>
      ))}
      {found.length > 0 && (
        <dl className="flex flex-col gap-3.5">
          {found.map(({ section, value }) => {
            const Icon = section.icon;
            const bullets = section.list ? items(value) : [];
            return (
              <div key={section.label} className="flex items-start gap-3">
                <span className={`grid size-7 shrink-0 place-items-center rounded-control ${section.tone}`} aria-hidden>
                  <Icon className="size-3.5" />
                </span>
                <div className="min-w-0 flex-1">
                  <dt className="text-[13px] font-semibold text-fg">{section.label}</dt>
                  <dd className="mt-0.5 text-[14px] leading-relaxed text-fg-2">
                    {bullets.length > 1 ? (
                      <ul className="flex flex-col gap-1">
                        {bullets.map((b, i) => (
                          <li key={i} className="flex gap-2">
                            <span className="mt-[9px] size-1 shrink-0 rounded-full bg-fg-3" aria-hidden />
                            <span>{b}</span>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      cap(bullets[0] ?? value)
                    )}
                  </dd>
                </div>
              </div>
            );
          })}
        </dl>
      )}
    </div>
  );
}
