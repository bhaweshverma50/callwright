import { FlowArrow } from "@phosphor-icons/react";
import { ArrowRight, ChevronLeft, Languages, Tag } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { useVoiceCatalog } from "../../api/agents";
import { createFlowAgent } from "../../api/flows";
import { problemMessage } from "../../api/problems";
import { Button, Field, Input, Select, Skeleton, toast } from "../../components";

/**
 * Create a flow agent (T020, FR-001): a name and a language. The agent gets that language's
 * voice and speech defaults, and the canvas opens with Start, Agent and End already connected.
 */
export function NewFlowAgentPage() {
  const voice = useVoiceCatalog();
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [language, setLanguage] = useState("en-US");
  const [touched, setTouched] = useState(false);
  const [pending, setPending] = useState(false);
  const nameError = touched && !name.trim() ? "Agent name is required" : null;

  const submit = async () => {
    setTouched(true);
    if (!name.trim()) return;
    setPending(true);
    try {
      const out = await createFlowAgent(name.trim(), language);
      for (const w of out.warnings ?? []) toast({ title: "Language defaults", description: w });
      navigate(`/agents/${out.agent_id}/flow`, { replace: true });
    } catch (e) {
      toast({ tone: "error", title: "Not created", description: problemMessage(e, "agent") });
      setPending(false);
    }
  };

  return (
    <div className="mx-auto flex w-full max-w-[640px] flex-col">
      <Link to="/agents/new" className="link-underline mb-4 inline-flex w-fit items-center gap-1 rounded-inline text-[13px] text-fg-2 hover:text-fg">
        <ChevronLeft className="size-4" aria-hidden /> Agent type
      </Link>
      <section className="relative overflow-hidden rounded-feature border border-line bg-surface shadow-2">
        <div aria-hidden className="glow-backdrop pointer-events-none absolute inset-x-0 top-0 h-40 opacity-80" />
        <div className="relative flex flex-col gap-6 p-6 sm:p-8">
          <div className="flex items-center gap-3.5">
            <span className="grad-action grid size-12 place-items-center rounded-panel text-white shadow-glow">
              <FlowArrow weight="duotone" className="size-6" aria-hidden />
            </span>
            <div>
              <h1 className="font-display text-[22px] font-medium tracking-[-0.02em] text-fg sm:text-[24px]">New flow agent</h1>
              <p className="text-[13px] text-fg-3">Design the call as steps on a canvas.</p>
            </div>
          </div>
          <form
            className="flex flex-col gap-5"
            onSubmit={(e) => {
              e.preventDefault();
              void submit();
            }}
          >
            <Field label="Agent name" error={nameError} hint="Shown in the agent list, calls and reports.">
              {({ id, describedBy, invalid }) => (
                <Input
                  id={id}
                  autoFocus
                  inputSize="lg"
                  maxLength={80}
                  value={name}
                  placeholder="Clinic intake"
                  prefix={<Tag className="size-4" aria-hidden />}
                  onChange={(e) => setName(e.target.value)}
                  onBlur={() => setTouched(true)}
                  aria-describedby={describedBy}
                  aria-invalid={invalid || undefined}
                />
              )}
            </Field>
            <Field label="Language" hint="Sets the voice and speech recognition defaults; you can change them later.">
              {({ id, describedBy }) =>
                voice.data ? (
                  <Select
                    id={id}
                    describedBy={describedBy}
                    value={language}
                    onValueChange={setLanguage}
                    options={voice.data.languages.filter((l) => l.code !== "multi").map((l) => ({ value: l.code, label: l.label, meta: l.code }))}
                  />
                ) : (
                  <Skeleton className="h-10 w-full" />
                )
              }
            </Field>
            <ol className="grid grid-cols-1 gap-2 rounded-panel border border-line bg-surface-2/50 p-3 text-[12.5px] text-fg-2 sm:grid-cols-3">
              {["Start: greets the caller", "Conversation: your first step", "End: closes the call"].map((s, i) => (
                <li key={s} className="flex items-center gap-2">
                  <span className="grid size-5 shrink-0 place-items-center rounded-full bg-surface font-mono text-[11px] text-fg-3 shadow-1">
                    {i + 1}
                  </span>
                  {s}
                </li>
              ))}
            </ol>
            <div className="flex items-center justify-between gap-3">
              <span className="flex items-center gap-1.5 text-[12px] text-fg-3">
                <Languages className="size-3.5" aria-hidden /> {language}
              </span>
              <Button type="submit" variant="primary" icon={<ArrowRight aria-hidden />} pending={pending}>
                Create and open the canvas
              </Button>
            </div>
          </form>
        </div>
      </section>
    </div>
  );
}
