import { cn } from "./cn";

/** Placeholder block shaped like the content it stands in for. Hidden from assistive tech. */
export function Skeleton({ className }: { className?: string }) {
  return <span aria-hidden className={cn("block rounded-[4px] bg-surface-3 animate-shimmer", className)} />;
}

/** Announces a loading region once, for screen readers, while skeletons render visually. */
export function LoadingRegion({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div role="status" aria-live="polite" aria-busy="true">
      <span className="sr-only">{label}</span>
      {children}
    </div>
  );
}
