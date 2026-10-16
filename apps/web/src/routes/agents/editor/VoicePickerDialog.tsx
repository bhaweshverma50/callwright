import { useInfiniteQuery } from "@tanstack/react-query";
import { Check, CloudOff, RotateCcw, Search, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { fetchProviderVoices, type TtsProvider, type Voice, type VoiceCatalog } from "../../../api/agents";
import { problemMessage } from "../../../api/problems";
import { Button, Dialog, Input, Segmented, Select, Skeleton, cn } from "../../../components";
import { useDebounced } from "../../../lib/useDebounced";
import { PreviewButton, VoiceAvatar, VoiceTags } from "./VoiceAvatar";
import { usePreview } from "./usePreview";

type Gender = "all" | "female" | "male" | "neutral";

/**
 * Voice browser (FR-009, FR-045, T041). Search runs on the provider when it supports it and on the
 * loaded list otherwise; gender and language filters appear where the provider's data has them;
 * previews play where samples exist. A listing outage says so with a retry, and the current voice
 * stays selected.
 */
export function VoicePickerDialog({
  open,
  onOpenChange,
  provider,
  model,
  language,
  catalog,
  value,
  onChoose,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  provider: TtsProvider;
  model: string;
  language: string;
  catalog: VoiceCatalog;
  value: string;
  onChoose: (voice: Voice) => void;
}) {
  const listing = provider.voice_listing ?? { source: "live", server_search: false, gender_filter: false, language_filter: false, previews: false };
  const [search, setSearch] = useState("");
  const [gender, setGender] = useState<Gender>("all");
  const [lang, setLang] = useState<string>(language);
  const [picked, setPicked] = useState(value);
  const preview = usePreview();
  const q = useDebounced(search.trim(), 250);
  const langLabel = (code: string) => catalog.languages.find((l) => l.code === code)?.label ?? code;

  useEffect(() => {
    if (open) {
      setPicked(value);
      setSearch("");
      setGender("all");
      setLang(language);
    } else preview.stop();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const filters = {
    ...(listing.server_search && q && { search: q }),
    ...(listing.gender_filter && gender !== "all" && { gender }),
    ...(listing.language_filter && lang !== "any" && { language: lang }),
    model,
  };
  const voices = useInfiniteQuery({
    queryKey: ["voices", "browse", provider.provider, filters],
    queryFn: ({ pageParam }) => fetchProviderVoices(provider.provider, filters, pageParam ?? undefined),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
    enabled: open,
    staleTime: 10 * 60_000,
    retry: false,
  });

  const items = useMemo(() => {
    const all = voices.data?.pages.flatMap((p) => p.items) ?? [];
    if (listing.server_search || !q) return all;
    const needle = q.toLowerCase();
    return all.filter((v) => v.name.toLowerCase().includes(needle) || (v.description ?? "").toLowerCase().includes(needle));
  }, [voices.data, listing.server_search, q]);

  const chosen = items.find((v) => v.voice_id === picked);
  const langOptions = [
    { value: "any", label: "Any language" },
    ...catalog.languages.filter((l) => l.code !== "multi").map((l) => ({ value: l.code, label: l.label })),
  ];

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      size="lg"
      title={`Choose a ${provider.label} voice`}
      description={
        listing.source === "curated" ? (
          <span className="inline-flex items-center gap-1.5">
            <ShieldCheck className="size-3.5 text-success-text" aria-hidden /> A reviewed list of business-ready voices.
          </span>
        ) : (
          "Search by name or description, then play a sample before you choose."
        )
      }
      footer={
        <>
          <Button onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button
            variant="primary"
            icon={<Check aria-hidden />}
            disabled={!chosen || picked === value}
            onClick={() => {
              if (chosen) onChoose(chosen);
              onOpenChange(false);
            }}
          >
            Use this voice
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          <Input
            className="min-w-0 flex-1"
            prefix={<Search aria-hidden />}
            placeholder={listing.server_search ? `Search ${provider.label} voices` : "Search these voices"}
            aria-label="Search voices"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          {listing.language_filter && (
            <Select className="sm:w-[200px]" aria-label="Language" value={lang} onValueChange={setLang} options={langOptions} />
          )}
        </div>
        {listing.gender_filter && (
          <Segmented
            aria-label="Gender"
            size="sm"
            value={gender}
            onValueChange={setGender}
            options={[
              { value: "all", label: "All" },
              { value: "female", label: "Female" },
              { value: "male", label: "Male" },
              { value: "neutral", label: "Neutral" },
            ]}
          />
        )}

        <div className="-mx-1 h-[min(46vh,420px)] overflow-y-auto px-1">
          {voices.isError ? (
            <div className="flex h-full flex-col items-start justify-center gap-3 px-2">
              <span className="grid size-10 place-items-center rounded-panel bg-warning-soft text-warning-text">
                <CloudOff className="size-5" aria-hidden />
              </span>
              <div>
                <p className="text-[14px] font-medium text-fg">{provider.label} voices did not load</p>
                <p className="text-[13px] text-fg-2">{problemMessage(voices.error, "voice list")} Your current voice stays selected.</p>
              </div>
              <Button size="sm" icon={<RotateCcw aria-hidden />} onClick={() => void voices.refetch()}>
                Try again
              </Button>
            </div>
          ) : voices.isPending ? (
            <ul className="flex flex-col gap-2" aria-label="Loading voices">
              {Array.from({ length: 6 }, (_, i) => (
                <li key={i} className="flex items-center gap-3 rounded-panel border border-line p-3">
                  <Skeleton className="size-10 rounded-full" />
                  <div className="flex flex-1 flex-col gap-1.5">
                    <Skeleton className="h-3 w-32" />
                    <Skeleton className="h-3 w-3/4" />
                  </div>
                </li>
              ))}
            </ul>
          ) : items.length === 0 ? (
            <div className="flex h-full flex-col items-start justify-center gap-1 px-2">
              <p className="text-[14px] font-medium text-fg">No voices match</p>
              <p className="text-[13px] text-fg-2">Try another name, or widen the language and gender filters.</p>
            </div>
          ) : (
            <div role="radiogroup" aria-label="Voices" className="flex flex-col gap-2 pb-1">
              {items.map((v) => {
                const on = v.voice_id === picked;
                return (
                  <div
                    key={v.voice_id}
                    role="radio"
                    aria-checked={on}
                    tabIndex={on || (!items.some((x) => x.voice_id === picked) && v === items[0]) ? 0 : -1}
                    onClick={() => setPicked(v.voice_id)}
                    onKeyDown={(e) => {
                      if (e.key === " " || e.key === "Enter") {
                        e.preventDefault();
                        setPicked(v.voice_id);
                      }
                      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
                        e.preventDefault();
                        const sib = (
                          e.key === "ArrowDown" ? e.currentTarget.nextElementSibling : e.currentTarget.previousElementSibling
                        ) as HTMLElement | null;
                        sib?.focus();
                      }
                    }}
                    className={cn(
                      "flex cursor-pointer items-center gap-3 rounded-panel border p-3 text-left transition-[background-color,border-color] duration-150",
                      "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
                      on ? "border-accent bg-accent-soft/45" : "border-line hover:border-accent/40 hover:bg-surface-2/60",
                    )}
                  >
                    <VoiceAvatar voice={v} selected={on} />
                    <div className="flex min-w-0 flex-1 flex-col gap-1">
                      <span className="flex min-w-0 items-center gap-2">
                        <span className="truncate text-[13.5px] font-semibold text-fg">{v.name}</span>
                        {v.voice_id === value && <span className="shrink-0 text-[12px] text-fg-3">Current</span>}
                      </span>
                      {v.description && <span className="line-clamp-2 text-[12.5px] leading-snug text-fg-2">{v.description}</span>}
                      <VoiceTags voice={v} languageLabel={langLabel} />
                    </div>
                    <PreviewButton voice={v} playing={preview.playing === v.voice_id} onToggle={() => preview.toggle(v.voice_id, v.preview_url!)} />
                  </div>
                );
              })}
              {voices.hasNextPage && (
                <Button
                  size="sm"
                  variant="ghost"
                  className="self-start"
                  pending={voices.isFetchingNextPage}
                  onClick={() => void voices.fetchNextPage()}
                >
                  Load more voices
                </Button>
              )}
            </div>
          )}
        </div>
        {!listing.previews && (
          <p className="text-[12.5px] text-fg-3">{provider.label} does not offer voice samples. Run a test call to hear a voice.</p>
        )}
      </div>
    </Dialog>
  );
}
