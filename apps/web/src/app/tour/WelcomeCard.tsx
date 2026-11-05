import * as RD from "@radix-ui/react-dialog";
import { AudioLines, Bot, Compass, PhoneCall, PhoneForwarded, Rocket } from "lucide-react";
import { useReducedMotion } from "motion/react";
import { useEffect, useState } from "react";
import { Button, FlowChain, type FlowNode } from "../../components";

const PATH: FlowNode[] = [
  { key: "agent", label: "Agent", icon: <Bot aria-hidden /> },
  { key: "voice", label: "Voice", icon: <AudioLines aria-hidden /> },
  { key: "call", label: "Test call", icon: <PhoneCall aria-hidden /> },
  { key: "publish", label: "Publish", icon: <Rocket aria-hidden /> },
  { key: "number", label: "Number", icon: <PhoneForwarded aria-hidden /> },
];

/**
 * First-run welcome (spec 013): shown once to a new user. The setup path is drawn as a chain whose
 * active link walks from agent to number. Start tour begins at the first step; Skip for now (or
 * Esc, or closing it) records the tour as skipped. The account menu's Guided setup restarts it.
 */
export function WelcomeCard({ onStart, onDecline }: { onStart: () => void; onDecline: () => void }) {
  const reduce = useReducedMotion() ?? false;
  const [lit, setLit] = useState(0);
  useEffect(() => {
    if (reduce) return;
    const t = window.setInterval(() => setLit((i) => (i + 1) % PATH.length), 1400);
    return () => window.clearInterval(t);
  }, [reduce]);

  return (
    <RD.Root open onOpenChange={(o) => !o && onDecline()}>
      <RD.Portal>
        <RD.Overlay className="fixed inset-0 z-40 bg-overlay backdrop-blur-[2px] data-[state=open]:animate-fade-in" />
        <RD.Content
          data-tour-ui
          aria-describedby="tour-welcome-body"
          onOpenAutoFocus={(e) => {
            e.preventDefault();
            document.getElementById("tour-welcome-start")?.focus();
          }}
          className="fixed left-1/2 top-1/2 z-50 flex max-h-[calc(100dvh-24px)] w-[calc(100vw-24px)] max-w-[560px] -translate-x-1/2 -translate-y-1/2 flex-col overflow-y-auto rounded-feature border border-line bg-surface shadow-pop focus:outline-none data-[state=open]:animate-pop-in"
        >
          <div className="relative overflow-hidden border-b border-line px-6 pb-6 pt-7">
            <FlowChain label="Setup path" nodes={PATH} active={PATH[lit]!.key} flow size="sm" stack="never" className="relative" />
          </div>
          <div className="px-6 pt-5">
            <span className="mb-3 grid size-9 place-items-center rounded-control bg-accent-soft text-accent-text">
              <Compass className="size-[18px]" aria-hidden />
            </span>
            <RD.Title className="font-display text-[22px] leading-tight tracking-[-0.02em] text-fg">Set up your first agent</RD.Title>
            <RD.Description id="tour-welcome-body" className="mt-2 text-[14px] leading-relaxed text-fg-2">
              About 3 minutes. The tour points at each control while you create an agent from a template, talk to it in your browser, publish it and
              put it on a number.
            </RD.Description>
            <p className="mt-3 text-[13px] leading-relaxed text-fg-3">
              Skip any step, or the whole tour. Guided setup in your account menu brings it back.
            </p>
          </div>
          <div className="mt-6 flex flex-wrap items-center justify-end gap-2 border-t border-line px-6 py-4">
            <Button variant="ghost" onClick={onDecline}>
              Skip for now
            </Button>
            <Button id="tour-welcome-start" variant="primary" icon={<Compass aria-hidden />} onClick={onStart}>
              Start tour
            </Button>
          </div>
        </RD.Content>
      </RD.Portal>
    </RD.Root>
  );
}
