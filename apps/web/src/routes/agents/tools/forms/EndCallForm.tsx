import { MessageSquareQuote } from "lucide-react";
import type { EndCallConfig } from "../../../../api/tools";
import { Field, Textarea } from "../../../../components";
import { FormSection } from "./FormSection";

export function EndCallForm({ config, onChange }: { config: EndCallConfig; onChange: (c: EndCallConfig) => void }) {
  const message = config.message ?? "";
  return (
    <FormSection
      title="Goodbye"
      icon={<MessageSquareQuote aria-hidden />}
      description="Usually left empty: the agent says its own goodbye, then hangs up. A line here is spoken after that goodbye."
    >
      <Field label="Goodbye line" hint={`${message.length} / 500`}>
        {({ id, describedBy }) => (
          <Textarea
            id={id}
            aria-describedby={describedBy}
            maxLength={500}
            className="min-h-20"
            placeholder="Thanks for calling. Goodbye!"
            value={message}
            onChange={(e) => onChange({ message: e.target.value || null })}
          />
        )}
      </Field>
    </FormSection>
  );
}
