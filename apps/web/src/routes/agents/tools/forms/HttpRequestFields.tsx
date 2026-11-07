import { Braces, Globe, Lock, LockOpen, MessageCircleMore, Plus, Rows3, Timer, Trash2, Variable } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import type { HeaderSpec, HttpMethod, HttpRequestConfig, ResponseMapping } from "../../../../api/tools";
import { Button, Field, IconButton, Input, Select, Switch, Textarea, Tooltip, cn } from "../../../../components";
import { urlError, type Errors } from "./fieldRules";
import { FormSection } from "./FormSection";
import { SecretHeaderInput } from "./SecretHeaderInput";
import { schemaLimits } from "../../../../lib/contract.gen";

export const METHODS: HttpMethod[] = ["GET", "POST", "PUT", "PATCH", "DELETE"];

const rowMotion = {
  layout: true,
  initial: { opacity: 0, y: -4 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, height: 0, marginTop: 0 },
  transition: { duration: 0.18 },
} as const;

/**
 * The HTTP request part shared by HTTP tools and 004's webhook nodes (T096, FR-046): method,
 * absolute https URL checked as it is typed, timeout 1 to 30 s, headers (secret or plain), body
 * template, response mappings and the waiting line.
 */
export function HttpRequestFields({
  value,
  onChange,
  errors,
  bodyText,
  onBodyText,
  allowHttp = false,
}: {
  value: HttpRequestConfig;
  onChange: (next: HttpRequestConfig) => void;
  errors: Errors;
  /** Raw body-template text (may be invalid JSON while typing). */
  bodyText: string;
  onBodyText: (text: string) => void;
  allowHttp?: boolean;
}) {
  const set = (patch: Partial<HttpRequestConfig>) => onChange({ ...value, ...patch });
  const headers = value.headers ?? [];
  const mappings = value.response_mappings ?? [];
  const setHeader = (i: number, patch: Partial<HeaderSpec>) => set({ headers: headers.map((h, j) => (j === i ? { ...h, ...patch } : h)) });
  const setMapping = (i: number, patch: Partial<ResponseMapping>) =>
    set({ response_mappings: mappings.map((m, j) => (j === i ? { ...m, ...patch } : m)) });
  const liveUrlError = value.url ? urlError(value.url, allowHttp) : null;
  const queryMethod = value.method === "GET" || value.method === "DELETE";

  return (
    <>
      <FormSection title="Request" icon={<Globe aria-hidden />} description="Use {{name}} for a parameter or call variable in the path and query.">
        <div className="grid grid-cols-[minmax(0,1fr)] gap-3 sm:grid-cols-[120px_minmax(0,1fr)]">
          <Field label="Method">
            {({ id }) => (
              <Select
                id={id}
                value={value.method}
                onValueChange={(m) => set({ method: m as HttpMethod })}
                options={METHODS.map((m) => ({ value: m, label: m }))}
              />
            )}
          </Field>
          <Field label="URL" error={liveUrlError} hint="Absolute https address.">
            {({ id, describedBy, invalid }) => (
              <Input
                id={id}
                className="font-mono"
                inputMode="url"
                spellCheck={false}
                placeholder="https://api.example.com/slots?date={{date}}"
                aria-describedby={describedBy}
                aria-invalid={invalid}
                value={value.url}
                onChange={(e) => set({ url: e.target.value })}
              />
            )}
          </Field>
        </div>
        <Field
          label="Timeout"
          error={errors.timeout_ms}
          hint="1 to 30 seconds. The request is not retried; on timeout the agent hears that the lookup failed."
        >
          {({ id, describedBy, invalid }) => (
            <Input
              id={id}
              type="number"
              min={1}
              max={30}
              className="w-[140px]"
              suffix={<span className="font-mono text-[12px]">s</span>}
              aria-describedby={describedBy}
              aria-invalid={invalid}
              value={Number.isFinite(value.timeout_ms) ? value.timeout_ms / 1000 : ""}
              onChange={(e) => set({ timeout_ms: e.target.value === "" ? Number.NaN : Math.round(Number(e.target.value) * 1000) })}
            />
          )}
        </Field>
      </FormSection>

      <FormSection
        title="Headers"
        icon={<Rows3 aria-hidden />}
        description="Lock a header to store its value encrypted. Stored secrets show only their last four characters."
        aside={
          <Button
            size="sm"
            icon={<Plus aria-hidden />}
            disabled={headers.length >= 20}
            onClick={() => set({ headers: [...headers, { name: "", value: "", secret: false }] })}
          >
            Add header
          </Button>
        }
      >
        {headers.length === 0 ? (
          <p className="rounded-control bg-surface-2/70 px-3 py-2.5 text-[13px] text-fg-3">No headers. Add one for an API key or a content type.</p>
        ) : (
          <ul className="flex flex-col gap-2" aria-label="Headers">
            <AnimatePresence initial={false}>
              {headers.map((h, i) => (
                <motion.li
                  key={i}
                  {...rowMotion}
                  className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-2 sm:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)_auto]"
                >
                  <div className="flex flex-col gap-1">
                    <Input
                      aria-label={`Header ${i + 1} name`}
                      className="font-mono"
                      placeholder="Authorization"
                      aria-invalid={Boolean(errors[`headers.${i}.name`])}
                      value={h.name}
                      onChange={(e) => setHeader(i, { name: e.target.value })}
                    />
                    {errors[`headers.${i}.name`] && <span className="text-[12px] text-danger-text">{errors[`headers.${i}.name`]}</span>}
                  </div>
                  <div className="order-3 col-span-2 flex flex-col gap-1 sm:order-none sm:col-span-1">
                    {h.secret ? (
                      <SecretHeaderInput
                        masked={h.masked_value}
                        value={h.value}
                        invalid={Boolean(errors[`headers.${i}.value`])}
                        onChange={(v) => setHeader(i, { value: v })}
                      />
                    ) : (
                      <Input
                        aria-label={`Header ${i + 1} value`}
                        className="font-mono"
                        placeholder="application/json"
                        aria-invalid={Boolean(errors[`headers.${i}.value`])}
                        value={h.value ?? ""}
                        onChange={(e) => setHeader(i, { value: e.target.value })}
                      />
                    )}
                    {errors[`headers.${i}.value`] && <span className="text-[12px] text-danger-text">{errors[`headers.${i}.value`]}</span>}
                  </div>
                  <div className="flex items-center">
                    <Tooltip content={h.secret ? "Secret: stored encrypted" : "Plain value: click to make it secret"}>
                      <button
                        type="button"
                        aria-pressed={h.secret}
                        aria-label={`Header ${i + 1} is secret`}
                        onClick={() =>
                          setHeader(i, h.secret ? { secret: false, value: "", masked_value: null } : { secret: true, value: h.value || null })
                        }
                        className={cn(
                          "grid size-9 place-items-center rounded-control transition-colors duration-150 [&_svg]:size-4",
                          h.secret ? "bg-accent text-white" : "text-fg-3 hover:bg-surface-2 hover:text-fg",
                        )}
                      >
                        {h.secret ? <Lock aria-hidden /> : <LockOpen aria-hidden />}
                      </button>
                    </Tooltip>
                    <IconButton
                      label={`Remove header ${h.name || i + 1}`}
                      className="hover:bg-danger-soft hover:text-danger-text"
                      onClick={() => set({ headers: headers.filter((_, j) => j !== i) })}
                    >
                      <Trash2 className="size-4" aria-hidden />
                    </IconButton>
                  </div>
                </motion.li>
              ))}
            </AnimatePresence>
          </ul>
        )}
      </FormSection>

      <FormSection
        title="Body"
        icon={<Braces aria-hidden />}
        description={
          queryMethod
            ? "Leave empty to send the parameters in the query string."
            : "Leave empty to send the parameters as the JSON body. A template is JSON with {{name}} inside string values."
        }
      >
        <Field label="Body template" hideLabel error={errors.body_template}>
          {({ id, describedBy, invalid }) => (
            <Textarea
              id={id}
              spellCheck={false}
              className="min-h-24 font-mono text-[13px]"
              placeholder={'{\n  "date": "{{date}}",\n  "caller": "{{caller_number}}"\n}'}
              aria-describedby={describedBy}
              aria-invalid={invalid}
              value={bodyText}
              onChange={(e) => onBodyText(e.target.value)}
            />
          )}
        </Field>
      </FormSection>

      <FormSection
        title="Response mapping"
        icon={<Variable aria-hidden />}
        description="Save values from the answer as call variables that later tools and the prompt can use."
        aside={
          <Button
            size="sm"
            icon={<Plus aria-hidden />}
            disabled={mappings.length >= 20}
            onClick={() => set({ response_mappings: [...mappings, { variable_name: "", json_path: "" }] })}
          >
            Add mapping
          </Button>
        }
      >
        {mappings.length > 0 && (
          <ul className="flex flex-col gap-2" aria-label="Response mappings">
            <AnimatePresence initial={false}>
              {mappings.map((m, i) => (
                <motion.li
                  key={i}
                  {...rowMotion}
                  className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]"
                >
                  <div className="flex flex-col gap-1">
                    <Input
                      aria-label={`Mapping ${i + 1} variable`}
                      className="font-mono"
                      prefix={<Variable aria-hidden />}
                      placeholder="next_slot"
                      aria-invalid={Boolean(errors[`mappings.${i}.variable_name`])}
                      value={m.variable_name}
                      onChange={(e) => setMapping(i, { variable_name: e.target.value })}
                    />
                    {errors[`mappings.${i}.variable_name`] && (
                      <span className="text-[12px] text-danger-text">{errors[`mappings.${i}.variable_name`]}</span>
                    )}
                  </div>
                  <div className="order-3 col-span-2 flex flex-col gap-1 sm:order-none sm:col-span-1">
                    <Input
                      aria-label={`Mapping ${i + 1} path`}
                      className="font-mono"
                      placeholder="data.slots[0].time"
                      aria-invalid={Boolean(errors[`mappings.${i}.json_path`])}
                      value={m.json_path}
                      onChange={(e) => setMapping(i, { json_path: e.target.value })}
                    />
                    {errors[`mappings.${i}.json_path`] && <span className="text-[12px] text-danger-text">{errors[`mappings.${i}.json_path`]}</span>}
                  </div>
                  <IconButton
                    label={`Remove mapping ${m.variable_name || i + 1}`}
                    className="hover:bg-danger-soft hover:text-danger-text"
                    onClick={() => set({ response_mappings: mappings.filter((_, j) => j !== i) })}
                  >
                    <Trash2 className="size-4" aria-hidden />
                  </IconButton>
                </motion.li>
              ))}
            </AnimatePresence>
          </ul>
        )}
      </FormSection>

      <FormSection title="While it runs" icon={<Timer aria-hidden />}>
        <Switch
          checked={value.speak_during_execution}
          onCheckedChange={(on) => set({ speak_during_execution: on })}
          icon={<MessageCircleMore aria-hidden />}
          label="Say a waiting line"
          description="Spoken at once when the agent calls this tool before saying anything, so the caller never sits in silence."
        />
        <AnimatePresence initial={false}>
          {value.speak_during_execution && (
            <motion.div
              key="line"
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              className="overflow-hidden"
            >
              <Field label="Waiting line" error={errors.execution_message}>
                {({ id, describedBy, invalid }) => (
                  <Input
                    id={id}
                    maxLength={schemaLimits.HttpRequestSpec.execution_message.maxLength}
                    aria-describedby={describedBy}
                    aria-invalid={invalid}
                    value={value.execution_message}
                    onChange={(e) => set({ execution_message: e.target.value })}
                  />
                )}
              </Field>
            </motion.div>
          )}
        </AnimatePresence>
      </FormSection>
    </>
  );
}
