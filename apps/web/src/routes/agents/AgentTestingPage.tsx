/**
 * `/agents/:id/testing`: the agent's Testing area. Two tabs: a browser test call (spec 003 US1,
 * FR-047) and single-turn test cases judged by an LLM (spec 008 US1, `?tab=cases`).
 *
 * The call itself is the shared `WebCallPanel` (microphone check, `POST /v1/sessions/web-call`,
 * LiveKit room). This page picks what it calls: the draft (latest saved changes) or the published
 * version, and the values of the variables that version declares. Empty fields send nothing, so
 * the variable's default applies. The per-minute price of that version's stack drives the
 * running cost estimate.
 *
 * While the hosted call servers start, the session request waits at the wake gate and the global
 * WakeOverlay covers the page; if they never start, the panel says so and nothing is charged.
 */
import { PhoneCall } from "@phosphor-icons/react";
import { Braces, ChevronLeft, ClipboardCheck, Headphones, Settings2 } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { useAgent, useVersionDetail, type AgentConfig, type DynamicVariable } from "../../api/agents";
import { isApiError } from "../../api/errors";
import { problemMessage } from "../../api/problems";
import { useQuote } from "../../api/queries";
import { Button, EmptyState, Field, Input, PageHeader, Panel, PanelLoader, Segmented, Skeleton, TabPanel, Tabs, WorkLayout } from "../../components";
import { WebCallPanel } from "../../webCall/WebCallPanel";
import { schemaLimits } from "../../lib/contract.gen";
import { toMicros } from "../../lib/money";
import { RecordNotFound } from "../NotFound";
import { quoteRequestFor } from "./editor/CostCard";
import { TestCasesTab } from "./testing/TestCasesTab";
import { agentPath, AGENTS_PATH, isAgentId } from "../../lib/paths";

export type TestTarget = "draft" | "published";

/** Values the operator typed for the declared variables; empty fields are left out. */
export function variablesToSend(declared: DynamicVariable[], values: Record<string, string>): Record<string, string> | undefined {
  const out: Record<string, string> = {};
  for (const v of declared) {
    const value = values[v.name];
    if (value !== undefined && value !== "") out[v.name] = value;
  }
  return Object.keys(out).length ? out : undefined;
}

export function AgentTestingPage() {
  const { id = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") === "cases" ? "cases" : "call";
  const valid = isAgentId(id);
  const agent = useAgent(valid ? id : undefined);
  const [target, setTarget] = useState<TestTarget>("draft");
  const [values, setValues] = useState<Record<string, string>>({});

  const detail = agent.data;
  const published = detail?.published_version ?? null;
  const testing: TestTarget = target === "published" && published ? "published" : "draft";
  const publishedVersion = useVersionDetail(id, testing === "published" && published ? published.id : null);
  const config: AgentConfig | undefined = testing === "draft" ? detail?.draft_config : publishedVersion.data?.config;
  const declared = useMemo(() => config?.dynamic_variables ?? [], [config]);
  const variables = useMemo(() => variablesToSend(declared, values), [declared, values]);

  const quote = useQuote(config ? quoteRequestFor(config) : null);
  const perMinute = quote.data?.per_minute_total_usd ? toMicros(quote.data.per_minute_total_usd) : null;

  if (!valid || (isApiError(agent.error) && agent.error.status === 404))
    return <RecordNotFound kind="agent" backTo={AGENTS_PATH} backLabel="Back to Agents" />;
  if (agent.error)
    return (
      <EmptyState icon={<PhoneCall weight="duotone" />} title="The agent did not load">
        {problemMessage(agent.error, "agent")}
      </EmptyState>
    );
  if (!detail) return <PanelLoader label="Opening agent" />;

  const editPath = agentPath(detail);
  const draftLabel = `Draft, version ${detail.draft_version.version_number}`;
  const publishedLabel = published ? `Published, version ${published.version_number}` : "Published";

  return (
    <div className="flex flex-col">
      <Link to={editPath} className="link-underline mb-4 inline-flex w-fit items-center gap-1 rounded-inline text-[13px] text-fg-2 hover:text-fg">
        <ChevronLeft className="size-4" aria-hidden /> Back to the agent
      </Link>
      <PageHeader
        title={`Test ${detail.name}`}
        description={
          tab === "cases"
            ? "Single-turn test cases: what a caller says and what the agent should do. Runs are judged by an LLM and charged as a feature charge."
            : "Call the agent from your browser. Each answer shows its latency by link of the chain; the call is charged like any other call."
        }
        actions={
          <Button asChild icon={<Settings2 aria-hidden />}>
            <Link to={editPath}>Edit agent</Link>
          </Button>
        }
      />
      <Tabs
        aria-label="Testing"
        value={tab}
        onValueChange={(v) => {
          const p = new URLSearchParams(params);
          if (v === "cases") p.set("tab", "cases");
          else p.delete("tab");
          setParams(p, { replace: true });
        }}
        items={[
          { value: "call", label: "Browser call", icon: <Headphones aria-hidden /> },
          { value: "cases", label: "Test cases", icon: <ClipboardCheck aria-hidden /> },
        ]}
      >
        <TabPanel value="cases">
          <TestCasesTab agent={detail} />
        </TabPanel>
        <TabPanel value="call">
          <WorkLayout
            main={<WebCallPanel agentId={id} version={testing} variables={variables} {...(perMinute !== null && { perMinuteMicros: perMinute })} />}
            inspector={
              <Panel title="Call setup" description="Changes apply to the next call." icon={<Settings2 aria-hidden />}>
                <div className="flex flex-col gap-5">
                  <div className="flex flex-col gap-2">
                    <span id="test-version-label" className="text-[13px] font-medium text-fg">
                      Version
                    </span>
                    <Segmented
                      aria-labelledby="test-version-label"
                      aria-describedby="test-version-hint"
                      value={testing}
                      onValueChange={setTarget}
                      fill
                      size="sm"
                      options={[
                        { value: "draft", label: "Draft" },
                        { value: "published", label: "Published", disabled: !published },
                      ]}
                    />
                    <p id="test-version-hint" className="text-[13px] text-fg-3">
                      {testing === "draft" ? `${draftLabel}: your latest saved changes.` : `${publishedLabel}: what live calls answer with.`}
                      {!published && " Publish the agent to test the live version."}
                    </p>
                  </div>

                  <section aria-labelledby="test-vars-title" className="flex flex-col gap-3">
                    <div className="flex items-center gap-2">
                      <Braces className="size-4 text-fg-3" aria-hidden />
                      <h3 id="test-vars-title" className="text-[13px] font-medium text-fg">
                        Variables
                      </h3>
                    </div>
                    {!config ? (
                      <Skeleton className="h-9 w-full" />
                    ) : declared.length === 0 ? (
                      <p className="text-[13px] text-fg-3">
                        This version declares no variables. Add them in the agent's prompt settings to personalise test calls.
                      </p>
                    ) : (
                      <>
                        {declared.map((v) => (
                          <Field
                            key={v.name}
                            label={<span className="font-mono text-[13px]">{v.name}</span>}
                            hint={v.description ?? (v.default ? `Empty uses the default, ${v.default}.` : "No default: empty leaves it unset.")}
                          >
                            {({ id: inputId, describedBy }) => (
                              <Input
                                id={inputId}
                                aria-describedby={describedBy}
                                maxLength={schemaLimits.DynamicVariable.default.maxLength}
                                placeholder={v.default ?? ""}
                                value={values[v.name] ?? ""}
                                onChange={(e) => setValues((prev) => ({ ...prev, [v.name]: e.target.value }))}
                              />
                            )}
                          </Field>
                        ))}
                      </>
                    )}
                  </section>
                </div>
              </Panel>
            }
          />
        </TabPanel>
      </Tabs>
    </div>
  );
}
