import { motion, useReducedMotion } from "motion/react";
import { COMPONENT_ICONS, COMPONENT_LABELS, cn } from "../../../components";
import { catalogV1 } from "../../../lib/catalogSeed";
import { providerLabel } from "../../../lib/providers";

/** Every vendor in the catalog, tagged with the link of the chain it fills. */
const VENDORS = (() => {
  const seen = new Map<string, string>();
  for (const e of catalogV1.entries) if (e.component !== "platform" && !seen.has(e.provider)) seen.set(e.provider, e.component);
  return [...seen].map(([provider, component]) => ({ name: providerLabel(provider), component }));
})();

/** A slow strip of the vendors a call can run on. Static under reduced motion. */
export function ProviderStrip() {
  const reduce = useReducedMotion();
  const items = (copy: number) =>
    VENDORS.map((v) => {
      const Icon = COMPONENT_ICONS[v.component]!;
      return (
        <li key={`${copy}-${v.name}`} aria-hidden={copy > 0 || undefined} className="flex shrink-0 items-center gap-2.5 pr-12">
          <Icon className="size-4 text-fg-3" aria-hidden />
          <span className="text-[17px] font-medium tracking-[-0.01em] text-fg-2">{v.name}</span>
          <span className="sr-only">, {COMPONENT_LABELS[v.component]}</span>
        </li>
      );
    });
  return (
    <section aria-label="Vendors you can use" className="border-y border-line">
      <div className="mx-auto flex max-w-[1200px] flex-col gap-4 px-4 py-6 sm:px-6 md:flex-row md:items-center md:gap-10">
        <p className="shrink-0 text-[14px] text-fg-3">Runs on the vendors you already use</p>
        <div
          className={cn(
            "min-w-0 flex-1 overflow-hidden",
            !reduce && "[mask-image:linear-gradient(to_right,transparent,black_8%,black_92%,transparent)]",
          )}
        >
          {reduce ? (
            <ul className="flex flex-wrap gap-y-3 [&>li]:pr-8">{items(0)}</ul>
          ) : (
            <motion.ul className="flex w-max" animate={{ x: ["0%", "-50%"] }} transition={{ duration: 45, ease: "linear", repeat: Infinity }}>
              {items(0)}
              {items(1)}
            </motion.ul>
          )}
        </div>
      </div>
    </section>
  );
}
