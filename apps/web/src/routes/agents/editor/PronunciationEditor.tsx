import { BookA, Plus, Trash2 } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useRef } from "react";
import { Button, IconButton, Input } from "../../../components";
import { FieldError, StackRow } from "./fields";
import type { AgentDraft } from "./useAgentDraft";
import { fieldId } from "../config/fields";
import { schemaLimits } from "../../../lib/contract.gen";

/**
 * Pronunciation dictionary (FR-005): words are replaced before the voice speaks them. Rows with an
 * empty word or replacement are dropped on save; the same word twice (ignoring case) is flagged.
 */
export function PronunciationEditor({ draft }: { draft: AgentDraft }) {
  const rows = draft.config.advanced.pronunciation;
  const keys = useRef<number[]>([]);
  const seq = useRef(0);
  while (keys.current.length < rows.length) keys.current.push(++seq.current);
  keys.current.length = rows.length;
  const key = (w: string) => `/advanced/pronunciation[${w.trim().toLowerCase()}]`;

  return (
    <StackRow
      icon={<BookA />}
      label="Words to replace"
      description="Teach the voice names and terms it says wrong. Each word is replaced before it is spoken."
      actions={
        <Button
          size="sm"
          icon={<Plus aria-hidden />}
          disabled={rows.length >= 200}
          onClick={() => draft.update((c) => void c.advanced.pronunciation.push({ word: "", replacement: "" }))}
        >
          Add word
        </Button>
      }
    >
      {rows.length === 0 ? (
        <p className="rounded-control border border-dashed border-line-strong px-4 py-3.5 text-[13px] text-fg-3">
          No entries. For example, say <span className="text-fg-2">SQL</span> as <span className="text-fg-2">sequel</span>.
        </p>
      ) : (
        <div className="overflow-hidden rounded-control border border-line">
          <div className="hidden grid-cols-[minmax(0,1fr)_minmax(0,1fr)_32px] gap-3 border-b border-line bg-surface-2/70 px-3 py-2 text-[12px] font-medium text-fg-3 sm:grid">
            <span>Word</span>
            <span>Say it as</span>
            <span className="sr-only">Remove</span>
          </div>
          <ul className="divide-y divide-line">
            <AnimatePresence initial={false}>
              {rows.map((r, i) => {
                const err = r.word.trim() ? (draft.errorFor(`${key(r.word)}/word`) ?? draft.errorFor(`${key(r.word)}/replacement`)) : null;
                return (
                  <motion.li
                    key={keys.current[i]}
                    initial={{ opacity: 0, y: -4 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0 }}
                    transition={{ duration: 0.16 }}
                    className="flex flex-col gap-1.5 px-3 py-2.5"
                  >
                    <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_32px] items-center gap-3">
                      <Input
                        id={r.word.trim() ? fieldId(`${key(r.word)}/word`) : undefined}
                        inputSize="sm"
                        aria-label={`Word ${i + 1}`}
                        placeholder="SQL"
                        value={r.word}
                        maxLength={schemaLimits.PronunciationEntry.word.maxLength}
                        aria-invalid={Boolean(err)}
                        onChange={(e) => draft.update((c) => void (c.advanced.pronunciation[i]!.word = e.target.value))}
                        onBlur={() => r.word.trim() && draft.touch(`${key(r.word)}/word`)}
                      />
                      <Input
                        inputSize="sm"
                        aria-label={`Say word ${i + 1} as`}
                        placeholder="sequel"
                        value={r.replacement}
                        maxLength={schemaLimits.PronunciationEntry.replacement.maxLength}
                        onChange={(e) => draft.update((c) => void (c.advanced.pronunciation[i]!.replacement = e.target.value))}
                      />
                      <IconButton
                        label={`Remove ${r.word.trim() || `entry ${i + 1}`}`}
                        className="size-8"
                        onClick={() => {
                          keys.current.splice(i, 1);
                          draft.update((c) => void c.advanced.pronunciation.splice(i, 1));
                        }}
                      >
                        <Trash2 className="size-4" aria-hidden />
                      </IconButton>
                    </div>
                    <FieldError message={err} />
                  </motion.li>
                );
              })}
            </AnimatePresence>
          </ul>
        </div>
      )}
    </StackRow>
  );
}
