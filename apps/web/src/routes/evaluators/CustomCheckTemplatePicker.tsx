import { ArrowRight, CircleDollarSign, MessageCircleQuestion, TextSearch } from "lucide-react";
import { motion } from "motion/react";
import type { CustomType } from "../../api/quality";
import { Badge, cn, focusRing } from "../../components";

const TEMPLATES: { type: CustomType; title: string; body: string; example: string; icon: typeof TextSearch; free: boolean }[] = [
  {
    type: "phrase_check",
    title: "Required or forbidden phrase",
    body: "Checks what the agent or caller said for a phrase or pattern: a disclosure that must be read, a promise that must never be made.",
    example: 'Forbid "guaranteed approval" in agent turns',
    icon: TextSearch,
    free: true,
  },
  {
    type: "llm_judge_custom",
    title: "Custom judge question",
    body: "A model reads the call and answers your yes or no question. You choose which answer counts as a pass.",
    example: "Did the agent confirm the caller's date of birth?",
    icon: MessageCircleQuestion,
    free: false,
  },
];

/** Step one of "Add custom check" (FR-044): pick a template, then fill its form. */
export function CustomCheckTemplatePicker({ onPick }: { onPick: (type: CustomType) => void }) {
  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-3 pb-2 sm:grid-cols-2" role="list" aria-label="Templates">
      {TEMPLATES.map((t, i) => {
        const Icon = t.icon;
        return (
          // A list item holding a button (a button cannot take the listitem role).
          <motion.div
            key={t.type}
            role="listitem"
            className="flex"
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.06, duration: 0.25 }}
          >
            <button
              type="button"
              onClick={() => onPick(t.type)}
              aria-label={t.title}
              aria-describedby={`tpl-${t.type}-body`}
              className={cn(
                "group relative flex w-full cursor-pointer flex-col gap-3 overflow-hidden rounded-panel border border-line bg-surface p-4 text-left",
                "transition-[border-color,box-shadow,transform] duration-200 hover:-translate-y-0.5 hover:border-accent/50 hover:shadow-glow",
                focusRing,
              )}
            >
              <span
                aria-hidden
                className="pointer-events-none absolute -right-10 -top-10 size-32 rounded-full bg-[radial-gradient(closest-side,var(--glow-b),transparent)]"
              />
              <span className="flex w-full items-center justify-between">
                <span className="grad-action grid size-10 place-items-center rounded-control text-white shadow-[0_8px_20px_-10px_rgb(51_70_232/0.8)] [&_svg]:size-5">
                  <Icon aria-hidden />
                </span>
                {t.free ? (
                  <Badge tone="success">Free</Badge>
                ) : (
                  <Badge tone="warning" icon={<CircleDollarSign aria-hidden />}>
                    Costs credit per call
                  </Badge>
                )}
              </span>
              <span className="flex w-full flex-col gap-1">
                <span className="text-[14px] font-semibold text-fg">{t.title}</span>
                <span id={`tpl-${t.type}-body`} className="text-[12.5px] leading-relaxed text-fg-2">
                  {t.body}
                </span>
              </span>
              <span className="rounded-control bg-surface-2 px-2.5 py-2 font-mono text-[11.5px] text-fg-2">{t.example}</span>
              <span className="mt-auto inline-flex items-center gap-1 text-[12.5px] font-medium text-accent-text">
                Use this template
                <ArrowRight className="size-3.5 transition-transform duration-200 group-hover:translate-x-0.5" aria-hidden />
              </span>
            </button>
          </motion.div>
        );
      })}
    </div>
  );
}
