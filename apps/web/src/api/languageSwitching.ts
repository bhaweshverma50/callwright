/**
 * Caller language switching (spec 012): which languages a caller can switch an agent to, the
 * same rule as services/api app/caller_language/options.py. A catalog language (never "multi")
 * is supported when the agent's speech recognition provider has a model for that exact code and
 * the agent's voice model speaks its base language ("hi" for "hi-Latn"), directly or through the
 * model's `multilingual_model` (English-only Flash v2 and Turbo v2 switch to their v2.5 versions).
 * The agent's own language and its other variants are never a switch target.
 */
import type { AgentConfig, Language, VoiceCatalog } from "./agents";

export type LanguageSwitching = NonNullable<AgentConfig["advanced"]["language_switching"]>;

/** The part before the first "-": "hi-Latn" -> "hi", "en-US" -> "en". */
export const baseLanguage = (code: string) => (code.split("-")[0] ?? code).toLowerCase();

/** The setting with the defaults for configs written before 012 (on, every language). */
export function languageSwitchingOf(config: Pick<AgentConfig, "advanced">): LanguageSwitching {
  const raw = config.advanced.language_switching;
  return { enabled: raw?.enabled !== false, languages: Array.isArray(raw?.languages) ? raw.languages : [] };
}

export interface SpeechStack {
  language: string;
  stt: { provider: string };
  tts: { provider: string; model: string };
}

/**
 * Every catalog language the agent's speech recognition and voice both handle, in catalog order,
 * including its own (validation warns only about codes outside this list).
 */
export function supportedLanguages(catalog: VoiceCatalog, stack: SpeechStack): Language[] {
  const stt = catalog.stt.find((p) => p.provider === stack.stt.provider);
  const voice = catalog.tts.find((p) => p.provider === stack.tts.provider);
  const model = voice?.models.find((m) => m.id === stack.tts.model);
  if (!stt || !voice || !model) return [];
  const multi = model.multilingual_model ? voice.models.find((m) => m.id === model.multilingual_model) : undefined;
  const spoken = new Set([...(model.languages ?? []), ...(multi?.languages ?? [])]);
  const heard = new Set(stt.models.filter((m) => !m.withdrawn).flatMap((m) => m.languages));
  return catalog.languages.filter((l) => l.code !== "multi" && heard.has(l.code) && spoken.has(baseLanguage(l.code)));
}

/** The languages the editor offers: supported ones other than the agent's own language. */
export function switchTargets(catalog: VoiceCatalog, stack: SpeechStack): Language[] {
  const own = stack.language === "multi" ? null : baseLanguage(stack.language);
  return supportedLanguages(catalog, stack).filter((l) => baseLanguage(l.code) !== own);
}

/**
 * What callers get when the list is empty: one code per base language, the bare code when it is
 * supported ("hi" rather than "hi-Latn"), else the first supported variant in catalog order.
 */
export function onePerBase(targets: Language[]): Language[] {
  const byBase = new Map<string, Language>();
  for (const l of targets) {
    const b = baseLanguage(l.code);
    const current = byBase.get(b);
    if (!current || (l.code === b && current.code !== b)) byBase.set(b, l);
  }
  return [...byBase.values()];
}
