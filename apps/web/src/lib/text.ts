/** Transcript line references the models cite, like "[12]", "[6-8]" or "[8, 10-11]". */
const LINE_REFS = /\s*\[\d+(?:\s*[-,]\s*\d+)*\]/g;

/** Model text for people: drop transcript line references (the cited lines are shown separately
 * as evidence where it matters). */
export function withoutLineRefs(text: string): string;
export function withoutLineRefs(text: string | null | undefined): string | null | undefined;
export function withoutLineRefs(text: string | null | undefined) {
  return text == null ? text : text.replace(LINE_REFS, "");
}
