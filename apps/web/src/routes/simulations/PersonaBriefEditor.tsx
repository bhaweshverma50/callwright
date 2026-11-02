/**
 * Persona brief (US4, T073): who the simulated caller is. Written from scratch for a standalone
 * run, or shown read-only when the system extracted it from a base call.
 */
import { UserRound } from "lucide-react";
import { useState } from "react";
import type { PersonaBrief } from "../../api/simulations";
import { Badge, Field, Input, Textarea } from "../../components";

export const emptyBrief = (): PersonaBrief => ({
  goal: "",
  known_facts: [],
  temperament: "",
  speaking_style: "",
  constraints: [],
  opening_line: null,
});

const lines = (text: string) =>
  text
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);

/** The brief as sent: blank optional parts left out. */
export function cleanBrief(b: PersonaBrief): PersonaBrief {
  return {
    goal: b.goal.trim(),
    ...(b.known_facts?.length && { known_facts: b.known_facts }),
    ...(b.temperament?.trim() && { temperament: b.temperament.trim() }),
    ...(b.speaking_style?.trim() && { speaking_style: b.speaking_style.trim() }),
    ...(b.constraints?.length && { constraints: b.constraints }),
    ...(b.opening_line?.trim() && { opening_line: b.opening_line.trim() }),
  };
}

/** A list typed one item per line; keeps the raw text so Enter starts a new line. */
function LinesInput({
  id,
  describedBy,
  rows,
  value,
  placeholder,
  onChange,
}: {
  id: string;
  describedBy?: string;
  rows: number;
  value: string[] | undefined;
  placeholder?: string;
  onChange: (items: string[]) => void;
}) {
  const [raw, setRaw] = useState((value ?? []).join("\n"));
  return (
    <Textarea
      id={id}
      aria-describedby={describedBy}
      rows={rows}
      value={raw}
      placeholder={placeholder}
      onChange={(e) => {
        setRaw(e.target.value);
        onChange(lines(e.target.value));
      }}
    />
  );
}

export function PersonaBriefEditor({
  value,
  onChange,
  goalError,
}: {
  value: PersonaBrief;
  onChange: (b: PersonaBrief) => void;
  goalError?: string | null;
}) {
  const set = (patch: Partial<PersonaBrief>) => onChange({ ...value, ...patch });
  return (
    <div className="flex flex-col gap-4">
      <Field label="Caller's goal" error={goalError} hint="What the caller wants by the end of the call.">
        {({ id, describedBy, invalid }) => (
          <Textarea
            id={id}
            aria-describedby={describedBy}
            aria-invalid={invalid}
            rows={2}
            maxLength={1000}
            value={value.goal}
            placeholder="Move Thursday's 3 pm cleaning to next week"
            onChange={(e) => set({ goal: e.target.value })}
          />
        )}
      </Field>
      <Field label="Facts the caller knows" hint="One per line. The caller shares them when it makes sense.">
        {({ id, describedBy }) => (
          <LinesInput
            id={id}
            describedBy={describedBy}
            rows={3}
            value={value.known_facts}
            placeholder={"Name: Priya Shah (gives it only when asked)\nDate of birth: 4 March 1991"}
            onChange={(known_facts) => set({ known_facts })}
          />
        )}
      </Field>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field label="Temperament">
          {({ id }) => (
            <Input
              id={id}
              maxLength={300}
              value={value.temperament ?? ""}
              placeholder="Short on time"
              onChange={(e) => set({ temperament: e.target.value })}
            />
          )}
        </Field>
        <Field label="Speaking style">
          {({ id }) => (
            <Input
              id={id}
              maxLength={300}
              value={value.speaking_style ?? ""}
              placeholder="Brief answers, no small talk"
              onChange={(e) => set({ speaking_style: e.target.value })}
            />
          )}
        </Field>
      </div>
      <Field label="Constraints" hint="Optional, one per line. For example: cannot come in on Mondays.">
        {({ id, describedBy }) => (
          <LinesInput id={id} describedBy={describedBy} rows={2} value={value.constraints} onChange={(constraints) => set({ constraints })} />
        )}
      </Field>
      <Field label="Opening line" hint="Optional. Leave blank to let the caller open naturally.">
        {({ id, describedBy }) => (
          <Input
            id={id}
            aria-describedby={describedBy}
            maxLength={500}
            value={value.opening_line ?? ""}
            placeholder="Hi, I need to move my cleaning."
            onChange={(e) => set({ opening_line: e.target.value })}
          />
        )}
      </Field>
    </div>
  );
}

/** Read-only brief on the comparison view. */
export function PersonaBriefView({ brief, source }: { brief: PersonaBrief; source?: "extracted" | "provided" | null }) {
  const rows: [string, string | undefined | null][] = [
    ["Temperament", brief.temperament],
    ["Speaking style", brief.speaking_style],
    ["Opening line", brief.opening_line],
  ];
  return (
    <section aria-label="Persona brief" className="rounded-panel border border-line bg-surface shadow-1">
      <header className="flex flex-wrap items-center gap-2.5 border-b border-line px-5 py-3.5">
        <span className="grid size-7 place-items-center rounded-control bg-accent-soft text-accent-text">
          <UserRound className="size-4" aria-hidden />
        </span>
        <h2 className="text-[14px] font-semibold text-fg">Persona brief</h2>
        {source && (
          <Badge tone={source === "extracted" ? "accent" : "neutral"}>
            {source === "extracted" ? "Written from the base call" : "Written by you"}
          </Badge>
        )}
      </header>
      <div className="grid grid-cols-1 gap-x-8 gap-y-4 px-5 py-4 md:grid-cols-2">
        <div className="flex flex-col gap-1 md:col-span-2">
          <span className="text-[12px] text-fg-3">Goal</span>
          <p className="text-[13.5px] text-fg">{brief.goal}</p>
        </div>
        {(brief.known_facts?.length ?? 0) > 0 && (
          <div className="flex flex-col gap-1">
            <span className="text-[12px] text-fg-3">Knows</span>
            <ul className="flex list-disc flex-col gap-0.5 pl-4 text-[13px] text-fg-2">
              {brief.known_facts!.map((f) => (
                <li key={f}>{f}</li>
              ))}
            </ul>
          </div>
        )}
        {(brief.constraints?.length ?? 0) > 0 && (
          <div className="flex flex-col gap-1">
            <span className="text-[12px] text-fg-3">Constraints</span>
            <ul className="flex list-disc flex-col gap-0.5 pl-4 text-[13px] text-fg-2">
              {brief.constraints!.map((f) => (
                <li key={f}>{f}</li>
              ))}
            </ul>
          </div>
        )}
        {rows
          .filter(([, v]) => v)
          .map(([k, v]) => (
            <div key={k} className="flex flex-col gap-1">
              <span className="text-[12px] text-fg-3">{k}</span>
              <p className="text-[13px] text-fg-2">{v}</p>
            </div>
          ))}
      </div>
    </section>
  );
}
