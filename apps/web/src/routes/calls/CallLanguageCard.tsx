import { ArrowRight, BookmarkCheck, BookmarkX, Languages } from "lucide-react";
import { useCallLanguage, useForgetCallerPreference, type CallLanguage } from "../../api/callerLanguage";
import { problemMessage } from "../../api/problems";
import { Button, toast } from "../../components";
import { phoneLabel } from "./callbacks/format";
import { mss, timeAgo } from "../../lib/format";

const Strong = ({ children }: { children: string }) => <span className="font-medium text-fg">{children}</span>;

function headline(l: CallLanguage) {
  if (l.started_from === "saved_preference")
    return (
      <>
        Started in <Strong>{l.started_language.label}</Strong> (saved for this caller)
      </>
    );
  if (!l.switches.length)
    return (
      <>
        In <Strong>{l.started_language.label}</Strong> for the whole call
      </>
    );
  return (
    <>
      Started in <Strong>{l.started_language.label}</Strong>
    </>
  );
}

/**
 * The call's languages (spec 012), for its drawer: the language it started in (the caller's saved
 * one on a phone call), every switch the agent made, and for phone calls the language saved for
 * the caller's number with a Forget action. Browser calls never save one, so they show no saved row.
 */
export function CallLanguageCard({ callId }: { callId: string }) {
  const language = useCallLanguage(callId);
  const forget = useForgetCallerPreference();
  const l = language.data;
  if (!l) return null;
  const pref = l.caller_number ? l.preference : null;
  const number = phoneLabel(pref?.phone_number);
  const run = () => {
    if (!pref) return;
    forget.mutate(pref.id, {
      onSuccess: () =>
        toast({
          tone: "success",
          title: "Saved language forgotten",
          description: `The next call with ${number} starts in ${l.agent_language.label}.`,
        }),
      onError: (e) => toast({ tone: "error", title: "The saved language was not forgotten", description: problemMessage(e, "saved language") }),
    });
  };
  return (
    <section aria-label="Language" className="flex items-start gap-3 rounded-panel border border-line bg-surface px-4 py-3.5 shadow-1">
      <span className="grid size-7 shrink-0 place-items-center rounded-control bg-accent-soft text-accent-text" aria-hidden>
        <Languages className="size-3.5" strokeWidth={2.25} />
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <p className="text-[14px] leading-relaxed text-fg-2">{headline(l)}</p>
        {l.switches.length > 0 && (
          <ul className="flex flex-col gap-1" aria-label="Language switches">
            {l.switches.map((s, i) => (
              <li key={i} className="flex items-center gap-2 text-[13px] text-fg-2">
                <ArrowRight className="size-3.5 shrink-0 text-fg-3" aria-hidden />
                <span className="min-w-0">
                  Switched to <Strong>{s.to.label}</Strong>
                  {s.offset_ms != null && (
                    <>
                      {" "}
                      at <span className="font-mono text-fg tnum">{mss(s.offset_ms / 1000)}</span>
                    </>
                  )}
                </span>
              </li>
            ))}
          </ul>
        )}
        {pref && (
          <div className="mt-1.5 flex flex-wrap items-center justify-between gap-x-3 gap-y-2 border-t border-line pt-2.5">
            <p className="flex min-w-0 items-start gap-2 text-[13px] leading-relaxed text-fg-3">
              <BookmarkCheck className="mt-0.5 size-3.5 shrink-0 text-fg-3" aria-hidden />
              <span className="min-w-0">
                Saved for <span className="whitespace-nowrap font-mono text-fg-2 tnum">{number}</span>:{" "}
                <span className="font-medium text-fg">{pref.language.label}</span>, updated{" "}
                <time dateTime={pref.updated_at} className="whitespace-nowrap">
                  {timeAgo(pref.updated_at)}
                </time>
              </span>
            </p>
            <Button
              size="sm"
              variant="secondary"
              icon={<BookmarkX aria-hidden />}
              pending={forget.isPending}
              aria-label={`Forget the saved language for ${number}`}
              onClick={run}
            >
              Forget
            </Button>
          </div>
        )}
      </div>
    </section>
  );
}
