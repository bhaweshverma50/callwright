/** Opens the "Ask about your data" panel from anywhere (dashboard button, voice copilot hand-off). */
const EVENT = "cw:ask";

export function openAsk(question?: string) {
  window.dispatchEvent(new CustomEvent<{ question?: string }>(EVENT, { detail: { question } }));
}

export function onOpenAsk(handler: (question?: string) => void): () => void {
  const listener = (e: Event) => handler((e as CustomEvent<{ question?: string }>).detail?.question);
  window.addEventListener(EVENT, listener);
  return () => window.removeEventListener(EVENT, listener);
}
