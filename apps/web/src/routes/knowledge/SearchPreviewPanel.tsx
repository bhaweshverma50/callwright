import { useMutation } from "@tanstack/react-query";
import { FileSearch, Search, SearchX, Zap } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";
import { api, unwrap } from "../../api/client";
import type { SearchResponse } from "../../api/knowledge";
import { problemMessage } from "../../api/problems";
import { Badge, Button, Input, Panel } from "../../components";

/** Passages repeat their heading on the first line; the card shows it separately. */
function withoutHeading(content: string, heading?: string | null): string {
  return heading && content.startsWith(`${heading}\n`) ? content.slice(heading.length + 1) : content;
}

function pages(from?: number | null, to?: number | null): string | null {
  if (!from) return null;
  return to && to !== from ? `pages ${from}-${to}` : `page ${from}`;
}

/**
 * Preview search (T081): the same retrieval the agent runs during a call, so operators can check
 * that a question finds the right passage before going live.
 */
export function SearchPreviewPanel({ kbId, disabled }: { kbId: string; disabled?: boolean }) {
  const [query, setQuery] = useState("");
  const search = useMutation({
    mutationFn: (q: string) =>
      unwrap(
        api.POST("/knowledge-bases/{kb_id}/search", { params: { path: { kb_id: kbId } }, body: { query: q, top_k: 4 } }),
      ) as Promise<SearchResponse>,
  });
  const data = search.data;
  return (
    <Panel title="Try a question" icon={<FileSearch aria-hidden />} description="Runs the search the agent uses on calls.">
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (query.trim()) search.mutate(query.trim());
        }}
      >
        <Input
          className="min-w-0 flex-1"
          prefix={<Search aria-hidden />}
          placeholder="How long do refunds take?"
          aria-label="Question"
          maxLength={1000}
          disabled={disabled}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <Button type="submit" pending={search.isPending} disabled={disabled || !query.trim()}>
          Search
        </Button>
      </form>
      {disabled && <p className="mt-3 text-[13px] text-fg-3">Available once a document is ready.</p>}
      {search.isError && <p className="mt-3 text-[13px] text-danger-text">{problemMessage(search.error, "knowledge base")}</p>}
      <AnimatePresence mode="wait">
        {data && (
          <motion.div
            key={search.submittedAt}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            className="mt-4 flex flex-col gap-3"
          >
            <div className="flex flex-wrap items-center gap-1.5 text-[12px] text-fg-3">
              <Badge tone="accent" icon={<Zap />}>
                {(data.embedding_ms + data.query_ms).toLocaleString()} ms
              </Badge>
              {data.embedding_cache_hit && <Badge>Cached question</Badge>}
              <span className="ml-auto">
                {data.results.length} {data.results.length === 1 ? "passage" : "passages"}
              </span>
            </div>
            {data.results.length === 0 ? (
              <div className="flex items-start gap-2.5 rounded-control bg-surface-2/70 px-3 py-3 text-[13px] text-fg-2">
                <SearchX className="mt-0.5 size-4 shrink-0 text-fg-3" aria-hidden />
                Nothing relevant found. The agent would say it does not have that information.
              </div>
            ) : (
              <ol className="flex flex-col gap-2.5">
                {data.results.map((r, i) => (
                  <motion.li
                    key={r.chunk_id}
                    initial={{ opacity: 0, y: 6 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: i * 0.05 }}
                    className="flex flex-col gap-2 rounded-panel border border-line bg-surface p-3.5 shadow-1"
                  >
                    <div className="flex min-w-0 items-center gap-2">
                      <span className="grid size-6 shrink-0 place-items-center rounded-full bg-accent font-mono text-[11px] font-medium text-white">
                        {i + 1}
                      </span>
                      <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-fg">{r.file_name}</span>
                      <span className="shrink-0 text-[12px] text-fg-3">{pages(r.page_from, r.page_to)}</span>
                    </div>
                    {r.heading && <p className="text-[12px] font-medium text-accent-text">{r.heading}</p>}
                    <p className="line-clamp-4 text-[13px] leading-relaxed text-fg-2">{withoutHeading(r.content, r.heading)}</p>
                    <div className="flex items-center gap-2" aria-label={`Relevance ${Math.round(r.score * 100)}%`}>
                      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-3">
                        <motion.div
                          className="h-full rounded-full grad-heat"
                          initial={{ width: 0 }}
                          animate={{ width: `${Math.round(r.score * 100)}%` }}
                          transition={{ duration: 0.5, delay: 0.1 + i * 0.05 }}
                        />
                      </div>
                      <span className="w-9 text-right font-mono text-[12px] text-fg-3 tnum">{r.score.toFixed(2)}</span>
                    </div>
                  </motion.li>
                ))}
              </ol>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </Panel>
  );
}
