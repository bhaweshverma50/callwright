import { Phone } from "@phosphor-icons/react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AudioLines, BrainCircuit, Braces, Captions, MessageSquareQuote, PhoneIncoming, PhoneOutgoing, Wand2 } from "lucide-react";
import { useEffect, useRef } from "react";
import { useNavigate } from "react-router";
import { createAgentFromTemplate, idempotencyKey, useLlmCatalog, useTemplate, useVoiceCatalog, type TemplateSummary } from "../../api/agents";
import { problemMessage } from "../../api/problems";
import { Badge, Button, Dialog, Skeleton, TruncatedText, cn, toast } from "../../components";
import { languageLabel, llmLabel } from "./editor/catalogs";
import { CATEGORY_TINT, TEMPLATE_ICONS } from "./templateIcons";
import { agentEditPath } from "../../lib/paths";

/** Highlights `{{name}}` placeholders in template text. */
function Highlighted({ text }: { text: string }) {
  const parts = text.split(/(\{\{[^{}]+\}\})/g);
  return (
    <>
      {parts.map((p, i) =>
        /^\{\{[^{}]+\}\}$/.test(p) ? (
          <span key={i} className="rounded-inline bg-accent-soft/80 px-0.5 font-mono text-[12px] text-accent-text">
            {p}
          </span>
        ) : (
          <span key={i}>{p}</span>
        ),
      )}
    </>
  );
}

/**
 * Template preview (T075, US5.4): the greeting, the full prompt with its variables highlighted,
 * the variables with their defaults, and the stack it starts with. "Use template" creates the
 * agent once (Idempotency-Key, disabled while pending) and opens it in the editor.
 */
export function TemplatePreviewDialog({
  template,
  categoryLabel,
  onOpenChange,
}: {
  template: TemplateSummary | null;
  categoryLabel: string;
  onOpenChange: (o: boolean) => void;
}) {
  const detail = useTemplate(template?.id ?? null);
  const llm = useLlmCatalog();
  const voice = useVoiceCatalog();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const key = useRef(idempotencyKey());
  useEffect(() => {
    key.current = idempotencyKey();
  }, [template?.id]);

  const use = useMutation({
    mutationFn: () => createAgentFromTemplate(qc, detail.data!, key.current),
    onSuccess: (agent) => {
      const replaced = agent.warnings.find((w) => w.code === "component_replaced");
      toast({
        tone: "success",
        title: "Agent created from template",
        description: replaced?.message ?? `${agent.name} is saved as version 1. Adjust it and save again.`,
      });
      navigate(agentEditPath(agent.id));
    },
    onError: (e) => toast({ tone: "error", title: "Agent not created", description: problemMessage(e, "template") }),
  });

  const t = detail.data;
  const Glyph = template ? (TEMPLATE_ICONS[template.icon] ?? Phone) : Phone;
  const ttsProvider = voice.data?.tts.find((p) => p.provider === t?.config.tts.provider);
  const sttProvider = voice.data?.stt.find((p) => p.provider === t?.config.stt.provider);

  return (
    <Dialog
      open={template !== null}
      onOpenChange={(o) => !use.isPending && onOpenChange(o)}
      size="lg"
      icon={<Glyph weight="duotone" />}
      title={template?.name ?? ""}
      description={template?.description}
      footer={
        <>
          <Button onClick={() => onOpenChange(false)} disabled={use.isPending}>
            Cancel
          </Button>
          <Button variant="primary" icon={<Wand2 aria-hidden />} pending={use.isPending} disabled={!t} onClick={() => use.mutate()}>
            Use template
          </Button>
        </>
      }
    >
      {template && (
        <div className="flex max-h-[min(58vh,560px)] flex-col gap-4 overflow-y-auto pr-1">
          <div className="flex flex-wrap gap-1.5">
            <Badge className={cn(CATEGORY_TINT[template.category])}>{categoryLabel}</Badge>
            <Badge icon={template.direction === "inbound" ? <PhoneIncoming /> : <PhoneOutgoing />}>
              {template.direction === "inbound" ? "Answers calls" : "Places calls"}
            </Badge>
            {t && <Badge>{languageLabel(voice.data, t.config.language)}</Badge>}
          </div>
          {!t ? (
            <div className="flex flex-col gap-2">
              <Skeleton className="h-12 w-full rounded-control" />
              <Skeleton className="h-48 w-full rounded-control" />
            </div>
          ) : (
            <>
              <section className="flex flex-col gap-1.5">
                <h3 className="flex items-center gap-1.5 text-[13px] font-medium text-fg-3">
                  <MessageSquareQuote className="size-3.5" aria-hidden /> Greeting
                </h3>
                <p className="rounded-control bg-accent-soft/35 px-3.5 py-2.5 text-[14px] leading-relaxed text-fg">
                  <Highlighted text={t.config.begin_message ?? ""} />
                </p>
              </section>
              <section className="flex flex-col gap-1.5">
                <h3 className="text-[13px] font-medium text-fg-3">Prompt</h3>
                <div className="max-h-[260px] overflow-y-auto whitespace-pre-wrap rounded-control border border-line bg-surface-2/50 px-3.5 py-3 text-[13px] leading-relaxed text-fg-2">
                  <Highlighted text={t.config.prompt} />
                </div>
              </section>
              <section className="flex flex-col gap-1.5">
                <h3 className="flex items-center gap-1.5 text-[13px] font-medium text-fg-3">
                  <Braces className="size-3.5" aria-hidden /> Variables, with the defaults test calls use
                </h3>
                <dl className="divide-y divide-line overflow-hidden rounded-control border border-line">
                  {t.config.dynamic_variables.map((v) => (
                    <div key={v.name} className="flex items-center justify-between gap-4 px-3.5 py-2">
                      <dt className="font-mono text-[13px] text-accent-text">{`{{${v.name}}}`}</dt>
                      <dd className="min-w-0 text-[13px] text-fg">
                        <TruncatedText>{v.default}</TruncatedText>
                      </dd>
                    </div>
                  ))}
                </dl>
              </section>
              <section className="grid grid-cols-[minmax(0,1fr)] gap-2 sm:grid-cols-3">
                {[
                  { icon: <BrainCircuit />, label: "Model", value: llmLabel(llm.data, `${t.config.llm.provider}/${t.config.llm.model}`) },
                  {
                    icon: <AudioLines />,
                    label: "Voice",
                    value: `${ttsProvider?.label ?? t.config.tts.provider}, ${ttsProvider?.models.find((m) => m.id === t.config.tts.model)?.label ?? t.config.tts.model}`,
                  },
                  { icon: <Captions />, label: "Speech recognition", value: `${sttProvider?.label ?? t.config.stt.provider}, Auto` },
                ].map((f) => (
                  <div key={f.label} className="flex min-w-0 flex-col gap-0.5 rounded-control bg-surface-2/60 px-3 py-2.5">
                    <span className="flex items-center gap-1.5 text-[12px] text-fg-3 [&_svg]:size-3.5">
                      {f.icon}
                      {f.label}
                    </span>
                    <TruncatedText className="text-[13px] text-fg">{f.value}</TruncatedText>
                  </div>
                ))}
              </section>
            </>
          )}
        </div>
      )}
    </Dialog>
  );
}
