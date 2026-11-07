import { motion, useReducedMotion } from "motion/react";
import { COMPONENT_LABELS, cn } from "../../../components";
import { providerLabel } from "../../../lib/providers";
import { useCatalogEntries } from "../../../api/pricing";
import type { CatalogEntry } from "../../../api/types";

/**
 * Vendor wordmarks in public/logos/vendors, from each vendor's own site or brand kit (Sarvam,
 * AssemblyAI, Deepgram, Cartesia, ai-coustics, Sanas) or Lobe Icons (MIT: OpenAI, ElevenLabs, Fish
 * Audio, Microsoft Azure). Drawn as a mask so every mark takes the page's text colour in both
 * themes. `ratio` is the file's width over height; `h` evens out optical size between marks.
 */
const LOGOS: Record<string, { ratio: number; h: number }> = {
  deepgram: { ratio: 5.27, h: 22 },
  assemblyai: { ratio: 5.75, h: 24 },
  sarvam: { ratio: 6.31, h: 18 },
  azure_openai: { ratio: 7.46, h: 22 },
  openai: { ratio: 3.58, h: 24 },
  elevenlabs: { ratio: 7.29, h: 20 },
  cartesia: { ratio: 6.98, h: 22 },
  fishaudio: { ratio: 6.96, h: 21 },
  sanas: { ratio: 6.15, h: 19 },
  ai_coustics: { ratio: 5.87, h: 24 },
};

/** Every vendor in the catalog, tagged with the link of the chain it fills. */
function vendorsIn(entries: CatalogEntry[]) {
  const seen = new Map<string, CatalogEntry["component"]>();
  for (const e of entries) if (e.component !== "platform" && !seen.has(e.provider)) seen.set(e.provider, e.component);
  return [...seen].map(([provider, component]) => ({ provider, name: providerLabel(provider), component }));
}

function Wordmark({ provider, name }: { provider: string; name: string }) {
  const logo = LOGOS[provider];
  if (!logo) return <span className="text-[17px] font-medium tracking-[-0.01em] text-fg-2">{name}</span>;
  const src = `url(/logos/vendors/${provider.replace("_", "-")}.svg)`;
  return (
    <span
      aria-hidden
      className="block bg-fg-2 transition-colors duration-200 group-hover:bg-fg"
      style={{
        height: logo.h,
        width: Math.round(logo.h * logo.ratio),
        maskImage: src,
        WebkitMaskImage: src,
        maskSize: "contain",
        WebkitMaskSize: "contain",
        maskRepeat: "no-repeat",
        WebkitMaskRepeat: "no-repeat",
        maskPosition: "center",
        WebkitMaskPosition: "center",
      }}
    />
  );
}

/** A slow strip of the vendors a call can run on. Static under reduced motion. */
export function ProviderStrip() {
  const vendors = vendorsIn(useCatalogEntries());
  const reduce = useReducedMotion();
  const items = (copy: number) =>
    vendors.map((v) => (
      <li key={`${copy}-${v.provider}`} aria-hidden={copy > 0 || undefined} className="group flex shrink-0 items-center pr-14">
        <Wordmark provider={v.provider} name={v.name} />
        <span className="sr-only">
          {v.name}, {COMPONENT_LABELS[v.component]}
        </span>
      </li>
    ));
  return (
    <section aria-label="Vendors you can use" className="border-y border-line">
      <div className="mx-auto flex max-w-[1200px] flex-col gap-5 px-4 py-7 sm:px-6 md:flex-row md:items-center md:gap-10">
        <p className="shrink-0 text-[14px] text-fg-3">Runs on the vendors you already use</p>
        <div
          className={cn(
            "min-w-0 flex-1 overflow-hidden",
            !reduce && "[mask-image:linear-gradient(to_right,transparent,black_8%,black_92%,transparent)]",
          )}
        >
          {reduce ? (
            <ul className="flex flex-wrap items-center gap-y-5">{items(0)}</ul>
          ) : (
            <motion.ul
              className="flex w-max items-center"
              animate={{ x: ["0%", "-50%"] }}
              transition={{ duration: 50, ease: "linear", repeat: Infinity }}
            >
              {items(0)}
              {items(1)}
            </motion.ul>
          )}
        </div>
      </div>
    </section>
  );
}
