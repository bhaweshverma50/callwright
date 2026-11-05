import { PenLine, SlidersVertical } from "lucide-react";
import type { HttpToolConfig } from "../../../../api/tools";
import { Button, Field, Textarea } from "../../../../components";
import { PARAMETERS_EXAMPLE, type Errors } from "./fieldRules";
import { FormSection } from "./FormSection";
import { HttpRequestFields } from "./HttpRequestFields";

/** HTTP tool form (T049): the parameters the model fills in, then the shared request fields. */
export function HttpToolForm({
  config,
  errors,
  onChange,
  parametersText,
  onParametersText,
  bodyText,
  onBodyText,
  allowHttp,
}: {
  config: HttpToolConfig;
  errors: Errors;
  onChange: (c: HttpToolConfig) => void;
  parametersText: string;
  onParametersText: (t: string) => void;
  bodyText: string;
  onBodyText: (t: string) => void;
  allowHttp?: boolean;
}) {
  return (
    <>
      <FormSection
        title="Parameters"
        icon={<SlidersVertical aria-hidden />}
        description="A JSON Schema of what the model fills in from the conversation. Describe each field so the model knows what to ask for."
        aside={
          <Button
            size="sm"
            variant="ghost"
            icon={<PenLine aria-hidden />}
            onClick={() => onParametersText(JSON.stringify(PARAMETERS_EXAMPLE, null, 2))}
          >
            Use example
          </Button>
        }
      >
        <Field label="Parameters schema" hideLabel error={errors.parameters}>
          {({ id, describedBy, invalid }) => (
            <Textarea
              id={id}
              spellCheck={false}
              className="min-h-40 font-mono text-[13px] leading-relaxed"
              aria-describedby={describedBy}
              aria-invalid={invalid}
              value={parametersText}
              onChange={(e) => onParametersText(e.target.value)}
            />
          )}
        </Field>
      </FormSection>
      <HttpRequestFields
        value={config}
        onChange={(next) => onChange({ ...config, ...next })}
        errors={errors}
        bodyText={bodyText}
        onBodyText={onBodyText}
        allowHttp={allowHttp}
      />
    </>
  );
}
