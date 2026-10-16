import { useCallback, useEffect, useRef, useState } from "react";

/**
 * One audio preview at a time (voice samples, background sounds). Starting a second preview stops
 * the first; unmounting stops playback.
 */
export function usePreview() {
  const audio = useRef<HTMLAudioElement | null>(null);
  const [playing, setPlaying] = useState<string | null>(null);

  const stop = useCallback(() => {
    audio.current?.pause();
    audio.current = null;
    setPlaying(null);
  }, []);

  const toggle = useCallback(
    (id: string, url: string) => {
      if (playing === id) return stop();
      audio.current?.pause();
      const a = new Audio(url);
      audio.current = a;
      setPlaying(id);
      a.onended = () => setPlaying((p) => (p === id ? null : p));
      a.play().catch(() => setPlaying(null));
    },
    [playing, stop],
  );

  useEffect(() => stop, [stop]);
  return { playing, toggle, stop };
}
