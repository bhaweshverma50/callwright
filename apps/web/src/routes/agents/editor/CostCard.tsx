import { AudioLines, BrainCircuit, Captions, Clock3, Server, Volume2, Zap } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { AgentConfig, LlmCatalog, VoiceCatalog } from "../../../api/agents";
import { useBalance, useQuote } from "../../../api/queries";
import type { QuoteLine, QuoteRequest } from "../../../api/types";
import { Badge, FlowChain, InfoTip, MoneyText, Skeleton, TruncatedText, cn, type FlowNode } from "../../../components";
import { formatUsd, toMicros } from "../../../lib/money";
import { talkMinutes } from "../../../lib/stack";
import { useDebounced } from "../../../lib/useDebounced";
import { llmLabel } from "./catalogs";
import { surchargeRisk } from "./surchargeRisk";

type Link = "nc" | "stt" | "llm" | "tts";

/** The quote request for the agent's selections (001 POST /pricing/quote). */
export function quoteRequestFor(c: Pick<AgentConfig, "stt" | "llm" | "tts" | "noise_cancellation">): QuoteRequest {
  return {
    components: {
      stt: { provider: c.stt.provider, model: c.stt.model ?? null },
      llm: { provider: c.llm.provider, model: c.llm.model },
      tts: { provider: c.tts.provider, model: c.tts.model },
      nc: c.noise_cancellation ? { provider: c.noise_cancellation.provider, model: c.noise_cancellation.model } : null,
    },
  };
}

const ICONS: Record<Link | "platform", typeof Captions> = { nc: AudioLines, stt: Captions, llm: BrainCircuit, tts: Volume2, platform: Server };

/**
 * Live per-minute cost (US4, T066, T101): the agent's own signal chain, each link with its model and
 * rate, the platform fee, and a total that ticks to its new value. The link that just changed
 * lights up for a moment so cause and effect read together. Noise cancellation shows whenever it is
 * on (even at $0.0000); an unpriced link says so and marks the total incomplete; a long prompt adds
 * a surcharge-risk notice naming the model's input allowance.
 */
export function CostCard({ config, llm, voice }: { config: AgentConfig; llm: LlmCatalog | undefined; voice: VoiceCatalog | undefined }) {
  const selection = useMemo(
    () => quoteRequestFor(config),
    // Only the priced selections refetch the quote (T065), not every keystroke elsewhere.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [
      config.stt.provider,
      config.stt.model,
      config.llm.provider,
      config.llm.model,
      config.tts.provider,
      config.tts.model,
      config.noise_cancellation?.provider,
      config.noise_cancellation?.model,
    ],
  );
  const req = useDebounced(selection, 250);
  const quote = useQuote(req);
  const balance = useBalance({ pollMs: false });

  // Light the link whose selection changed.
  const prev = useRef(selection);
  const [lit, setLit] = useState<Link | null>(null);
  useEffect(() => {
    const p = prev.current.components;
    const n = selection.components;
    const key = (s: { provider: string; model?: string | null } | null | undefined) => (s ? `${s.provider}/${s.model ?? ""}` : "off");
    const changed = (["nc", "stt", "llm", "tts"] as Link[]).find((k) => key(p[k]) !== key(n[k]));
    prev.current = selection;
    if (!changed) return;
    setLit(changed);
    const t = window.setTimeout(() => setLit(null), 2200);
    return () => window.clearTimeout(t);
  }, [selection]);

  const lines = quote.data?.lines ?? [];
  const line = (c: string) => lines.find((l) => l.component === c);
  const sttProvider = voice?.stt.find((p) => p.provider === config.stt.provider);
  const ttsProvider = voice?.tts.find((p) => p.provider === config.tts.provider);
  const nc = config.noise_cancellation
    ? voice?.noise_cancellation.find((o) => o.provider === config.noise_cancellation!.provider && o.model === config.noise_cancellation!.model)
    : null;
  const llmModel = llm?.providers.find((p) => p.id === config.llm.provider)?.models.find((m) => m.id === config.llm.model);
  const risk = surchargeRisk(
    config.prompt,
    llmModel?.input_tokens_bundle_per_min ?? line("llm")?.bundles?.find((b) => b.unit === "llm_input_tokens")?.per_min,
  );

  const detail: Record<Link, string> = {
    nc: nc ? nc.label : "Off",
    stt: `${sttProvider?.label ?? config.stt.provider}, ${config.stt.model ? (sttProvider?.models.find((m) => m.id === config.stt.model)?.label ?? config.stt.model) : "Auto"}`,
    llm: `${llm?.providers.find((p) => p.id === config.llm.provider)?.label ?? config.llm.provider}, ${llmLabel(llm, `${config.llm.provider}/${config.llm.model}`)}`,
    tts: `${ttsProvider?.label ?? config.tts.provider}, ${ttsProvider?.models.find((m) => m.id === config.tts.model)?.label ?? config.tts.model}`,
  };
  const names: Record<Link, string> = { nc: "Noise cancellation", stt: "Speech recognition", llm: "Language model", tts: "Voice" };
  const order: Link[] = ["nc", "stt", "llm", "tts"];
  const nodes: FlowNode[] = order.map((k) => {
    const Icon = ICONS[k];
    return {
      key: k,
      label: names[k],
      icon: <Icon aria-hidden />,
      off: k === "nc" && !config.noise_cancellation,
      detail: <TruncatedText className="text-[12px] text-fg-3">{detail[k]}</TruncatedText>,
    };
  });

  const rate = (l: QuoteLine | undefined) =>
    !l ? null : l.status === "unpriced" || l.rate_per_min_usd == null ? (
      <span className="text-[12px] text-warning-text">Price unavailable</span>
    ) : (
      <MoneyText value={l.rate_per_min_usd} places={4} className="text-[13px] text-fg" />
    );

  const total = quote.data?.per_minute_total_usd;
  const minutes = total && balance.data ? talkMinutes(toMicros(balance.data.balance_usd) ?? 0n, toMicros(total) ?? 0n) : null;
  const platform = line("platform");

  return (
    <section aria-labelledby="cost-title" className="@container overflow-hidden rounded-panel border border-line bg-surface shadow-1">
      <header className="flex items-start justify-between gap-3 border-b border-line px-5 py-3.5">
        <div className="flex items-start gap-2.5">
          <Clock3 className="mt-0.5 size-4 text-fg-3" aria-hidden />
          <div className="flex flex-col gap-0.5">
            <h2 id="cost-title" className="text-[14px] font-semibold text-fg">
              Cost per minute
            </h2>
            <p className="text-[13px] text-fg-3">Updates as you change models and voices.</p>
          </div>
        </div>
        <InfoTip label="How the estimate works" side="left">
          Base price for one minute of call on this agent's chain, from the current price list. Each minute includes 20,000 input and 200 output model
          tokens and 750 voice characters; calls that use more are billed for extra minutes.
        </InfoTip>
      </header>

      <div className="px-5 pb-2 pt-4">
        <FlowChain
          label="This agent's signal chain"
          nodes={nodes}
          active={lit}
          flow={lit !== null}
          size="sm"
          stack="always"
          rowHeight={60}
          renderNode={(n, content) => (
            <div className="flow-node-body w-full">
              {content}
              <span className="ml-auto shrink-0 pl-2 text-right">
                {n.off ? (
                  <span className="text-[12px] text-fg-3">Not used</span>
                ) : quote.isPending ? (
                  <Skeleton className="h-3 w-14" />
                ) : (
                  rate(line(n.key))
                )}
              </span>
            </div>
          )}
        />
      </div>

      <div className="mx-5 flex items-center justify-between gap-3 border-t border-dashed border-line-strong py-3">
        <span className="flex items-center gap-2 text-[13px] text-fg-2">
          <Server className="size-3.5 text-fg-3" aria-hidden /> Platform fee
        </span>
        {quote.isPending ? <Skeleton className="h-3 w-14" /> : rate(platform)}
      </div>

      <div className="flex items-end justify-between gap-3 bg-surface-2/60 px-5 py-4">
        <div className="flex flex-col gap-1">
          <span className="text-[13px] font-medium text-fg">Total a minute</span>
          {quote.data && !quote.data.complete && (
            <Badge tone="warning" icon={<Zap />}>
              Incomplete: one price is missing
            </Badge>
          )}
        </div>
        <div className="flex flex-col items-end" aria-live="polite">
          {total ? (
            <span className={cn("transition-opacity", quote.isFetching && "opacity-70")}>
              <MoneyText value={total} places={4} animate className="text-[22px] font-semibold tracking-[-0.01em] text-fg" />
              <span className="ml-0.5 text-[13px] text-fg-3">/min</span>
            </span>
          ) : (
            <Skeleton className="h-6 w-24" />
          )}
        </div>
      </div>

      {minutes !== null && (
        <p className="border-t border-line px-5 py-3 text-[13px] text-fg-2">
          Your balance covers about <span className="font-mono text-fg tnum">{minutes.toLocaleString()}</span> minutes on this agent.
        </p>
      )}

      <AnimatePresence initial={false}>
        {risk?.risk && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="overflow-hidden"
          >
            <div className="heat-border mx-3 mb-3 rounded-control bg-warning-soft/70 px-4 py-3" role="status">
              <p className="flex items-center gap-1.5 text-[13px] font-semibold text-warning-text">
                <Zap className="size-3.5" aria-hidden /> Long prompt: calls may cost more
              </p>
              <p className="mt-1 text-[13px] leading-relaxed text-fg-2">
                A typical minute would send about <span className="font-mono tnum">{risk.perMinute.toLocaleString()}</span> input tokens, past the{" "}
                <span className="font-mono tnum">{risk.bundle.toLocaleString()}</span> included in each minute of {llmModel?.label ?? "the model"}.
                The extra is billed as a surcharge of about {surchargeText(line("llm")?.rate_per_min_usd, risk.perMinute / risk.bundle)} a minute.
              </p>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </section>
  );
}

function surchargeText(rate: string | null | undefined, multiplier: number): string {
  const micros = rate ? toMicros(rate) : null;
  if (!micros) return "the model rate";
  const extra = BigInt(Math.round(Number(micros) * Math.max(0, multiplier - 1)));
  return formatUsd(extra, { places: 4 });
}
