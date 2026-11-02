import { Pause, Play } from "lucide-react";
import { useInView, useReducedMotion } from "motion/react";
import { useEffect, useRef, useState } from "react";
import { cn, focusRing } from "../../../components";

/**
 * A short muted loop of the real app (recorded by scripts/record-tour.mjs). Plays only while in
 * view; under reduced motion it waits for the visitor to press play.
 */
export function ProductVideo() {
  const ref = useRef<HTMLVideoElement>(null);
  const reduce = useReducedMotion();
  const inView = useInView(ref, { amount: 0.4 });
  const [paused, setPaused] = useState(true);
  const [userPaused, setUserPaused] = useState(!!reduce);

  useEffect(() => {
    const v = ref.current;
    if (!v) return;
    if (inView && !userPaused) void v.play().catch(() => setPaused(true));
    else v.pause();
  }, [inView, userPaused]);

  const toggle = () => {
    const v = ref.current;
    if (!v) return;
    if (v.paused) {
      setUserPaused(false);
      void v.play();
    } else {
      setUserPaused(true);
      v.pause();
    }
  };

  return (
    <div className="group relative overflow-hidden rounded-feature border border-line bg-console shadow-2">
      <video
        ref={ref}
        className="block aspect-[16/10] w-full"
        muted
        loop
        playsInline
        preload="metadata"
        poster="/media/tour-poster.jpg"
        onPlay={() => setPaused(false)}
        onPause={() => setPaused(true)}
        aria-label="Callwright tour: building an agent, a live test call, and the call's transcript, latency and cost"
      >
        <source src="/media/tour.webm" type="video/webm" />
        <source src="/media/tour.mp4" type="video/mp4" />
      </video>
      <button
        type="button"
        onClick={toggle}
        aria-label={paused ? "Play the tour" : "Pause the tour"}
        className={cn(
          "absolute bottom-4 right-4 grid size-10 cursor-pointer place-items-center rounded-full bg-[rgba(14,16,48,0.72)] text-white backdrop-blur transition-opacity duration-200",
          paused ? "opacity-100" : "opacity-0 group-hover:opacity-100 focus-visible:opacity-100",
          focusRing,
        )}
      >
        {paused ? <Play className="size-4" aria-hidden /> : <Pause className="size-4" aria-hidden />}
      </button>
    </div>
  );
}
