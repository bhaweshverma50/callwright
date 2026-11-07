import { FlaskConical } from "lucide-react";
import { useState } from "react";
import type { WebhookConfig } from "../../../../api/flows";
import { Field, Textarea } from "../../../../components";
import { HttpRequestFields } from "../../../agents/tools/forms/HttpRequestFields";
import { urlError, type Errors } from "../../../agents/tools/forms/fieldRules";
import { jsonError, timeoutError } from "./fieldRules";
import { Group, issueFor, type FormProps } from "./shared";

function bodyText(value: unknown): string {
  if (value === null || value === undefined || value === "") return "";
  return typeof value === "string" ? value : JSON.stringify(value, null, 2);
}

/**
 * Webhook node (FR-016, T028): the same request settings as HTTP tools (005's form), with
 * success and failure connections on the card, plus a canned response for simulations.
 */
export function WebhookForm({ config, onChange, issues, allowHttp }: FormProps<WebhookConfig>) {
  const [body, setBody] = useState(() => bodyText(config.request.body_template));
  const errors: Errors = {};
  const url = config.request.url ? urlError(config.request.url, allowHttp) : (issueFor(issues, "request.url") ?? null);
  if (url) errors.url = url;
  const timeout = timeoutError(config.request.timeout_ms);
  if (timeout) errors.timeout_ms = timeout;
  const bodyError = jsonError(body);
  if (bodyError) errors.body_template = bodyError;
  const mockError = config.mock_response ? jsonError(config.mock_response) : null;
  return (
    <>
      <div className="flex flex-col gap-5 px-5 py-5">
        <HttpRequestFields
          value={config.request}
          onChange={(request) => onChange({ ...config, request })}
          errors={errors}
          bodyText={body}
          onBodyText={(text) => {
            setBody(text);
            onChange({ ...config, request: { ...config.request, body_template: text.trim() ? text : null } });
          }}
          allowHttp={allowHttp}
        />
      </div>
      <Group
        title="Canned response"
        icon={<FlaskConical aria-hidden />}
        description="JSON returned instead of calling the URL in simulations. Mappings read from it too."
      >
        <Field label="Canned response" hideLabel error={mockError ?? issueFor(issues, "mock_response")}>
          {({ id, describedBy, invalid }) => (
            <Textarea
              id={id}
              rows={4}
              spellCheck={false}
              className="font-mono text-[12px]"
              placeholder='{"status": "shipped"}'
              value={config.mock_response ?? ""}
              onChange={(e) => onChange({ ...config, mock_response: e.target.value || null })}
              aria-describedby={describedBy}
              aria-invalid={invalid || undefined}
            />
          )}
        </Field>
      </Group>
    </>
  );
}
